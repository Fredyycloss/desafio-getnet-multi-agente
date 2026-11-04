"""Refresh the versioned knowledge snapshot from the official Getnet websites.

    python -m app.knowledge.ingest_cli [--max-pages 2000] [--render-js] [--embed]

Idempotent: chunks are keyed by content_hash; embeddings of unchanged chunks are reused
from the previous snapshot, so only new or changed text is embedded. Prints the manifest.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import logging
import os
import struct
import subprocess
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .crawler import Crawler, chunk_pages, extract_page, page_market, remove_boilerplate
from .ingest import SNAPSHOT_DIR, latest_snapshot

DOC_PREFIX = "search_document: "
THIN_PAGE_CHARS = 1200


def pack(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode()


def unpack(data: str) -> list[float]:
    raw = base64.b64decode(data)
    return list(struct.unpack(f"<{len(raw) // 2}e", raw))


def embed_text(chunk: dict) -> str:
    return f"{DOC_PREFIX}{chunk['title']} — {chunk['section']}\n{chunk['content']}"


def render_js(urls: list[str], frontend_dir: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        src.write_text(json.dumps(urls))
        proc = subprocess.run(["node", "scripts/render-pages.mjs", str(src), str(dst)], cwd=frontend_dir,
                              capture_output=True, text=True, timeout=60 * max(5, len(urls)))
        logging.info("render_js %s %s", proc.stdout.strip(), proc.stderr.strip()[-300:])
        return json.loads(dst.read_text()) if dst.exists() else {}


def section_of(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.hostname == "www.getnet.net":
        return f"getnet.net/{'/'.join(parts[:2]) or 'home'}"
    first = parts[0] if parts else "home"
    if first.startswith("get-ajuda"):
        return "get-ajuda"
    return first


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-pages", type=int, default=2000)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--render-js", action="store_true", help="render thin pages with Playwright (needs frontend deps)")
    parser.add_argument("--frontend-dir", default=str(Path(__file__).resolve().parents[3] / "frontend"))
    parser.add_argument("--embed", action="store_true", help="precompute nomic-embed-text vectors (needs Ollama)")
    parser.add_argument("--version", default=date.today().isoformat())
    parser.add_argument("--cache", default="", help="JSON file: reuse crawled pages if present, else save them there")
    args = parser.parse_args()
    timings: dict[str, float] = {}

    t0 = time.monotonic()
    crawler = Crawler(max_pages=args.max_pages, pause=args.pause)
    cache = Path(args.cache) if args.cache else None

    def save_cache() -> None:
        if cache:
            st = crawler.stats
            cache.write_text(json.dumps({"pages": pages, "stats": {
                "discovered": sorted(st.discovered), "fetched": st.fetched, "skipped": st.skipped, "failed": st.failed,
                "sitemap_urls": st.sitemap_urls, "stopped_by": getattr(st, "stopped_by", None),
                "unvisited": getattr(st, "unvisited", 0), "crawl_s": timings["crawl_s"]}}, ensure_ascii=False))

    if cache and cache.exists():
        cached = json.loads(cache.read_text())
        by_url: dict[str, dict] = {}
        for page in cached["pages"]:  # first copy of each final URL wins
            by_url.setdefault(page["url"], {**page, "blocks": [tuple(b) for b in page["blocks"]]})
        pages = list(by_url.values())
        st = crawler.stats
        st.discovered, st.fetched = set(cached["stats"]["discovered"]), cached["stats"]["fetched"]
        st.skipped, st.failed = cached["stats"]["skipped"], cached["stats"]["failed"]
        st.sitemap_urls, st.stopped_by, st.unvisited = cached["stats"]["sitemap_urls"], cached["stats"]["stopped_by"], cached["stats"]["unvisited"]
        timings["crawl_s"] = cached["stats"]["crawl_s"]
        # Incremental: entry points (and their links) not crawled yet.
        from .crawler import SEEDS
        from .ingest import canonicalize_url as canon
        missing = [s for s in SEEDS if canon(s) not in st.discovered]
        if missing:
            t_inc = time.monotonic()
            pages += crawler.crawl(seeds=missing, seen=set(st.discovered), known_pages=set(by_url), use_sitemaps=False)
            timings["crawl_s"] = round(timings["crawl_s"] + time.monotonic() - t_inc, 1)
    else:
        pages = crawler.crawl()
        timings["crawl_s"] = round(time.monotonic() - t0, 1)
    save_cache()

    rendered = [p["url"] for p in pages if p.get("rendered_js")]
    if args.render_js:
        t1 = time.monotonic()
        thin = [p["url"] for p in pages if not p.get("render_attempted") and sum(len(t) for _, t in p["blocks"]) < THIN_PAGE_CHARS]
        results = render_js(thin, Path(args.frontend_dir)) if thin else {}
        by_url = {p["url"]: p for p in pages}
        for url in thin:
            by_url[url]["render_attempted"] = True
        for url, item in results.items():
            if item.get("ok"):
                richer = extract_page(BeautifulSoup(item["html"], "html.parser"), url)
                if sum(len(t) for _, t in richer["blocks"]) > sum(len(t) for _, t in by_url[url]["blocks"]):
                    by_url[url].update(blocks=richer["blocks"], rendered_js=True)
                    rendered.append(url)
        timings["render_js_s"] = round(time.monotonic() - t1, 1)
        save_cache()

    removed = remove_boilerplate(pages)
    chunks = chunk_pages(pages)

    out_dir = SNAPSHOT_DIR / args.version
    out_dir.mkdir(parents=True, exist_ok=True)
    previous = latest_snapshot(exclude=args.version)
    old_vectors: dict[str, str] = {}
    old_hashes: set[str] = set()
    if previous:
        old_hashes = {c["content_hash"] for c in json.loads(gzip.decompress((previous / "chunks.json.gz").read_bytes()))}
        emb = previous / "embeddings.json.gz"
        if emb.exists():
            old_vectors = json.loads(gzip.decompress(emb.read_bytes()))["vectors"]

    model, vectors, embedded_now = None, {}, 0
    if args.embed:
        from ..infra.llm.ollama import OllamaProvider
        t2 = time.monotonic()
        provider = OllamaProvider()
        model = provider.embedding_model
        vectors = {c["content_hash"]: old_vectors[c["content_hash"]] for c in chunks if c["content_hash"] in old_vectors}
        missing = [c for c in chunks if c["content_hash"] not in vectors]
        for start in range(0, len(missing), 16):
            batch = missing[start:start + 16]
            for chunk, vector in zip(batch, provider.embed([embed_text(c) for c in batch])):
                vectors[chunk["content_hash"]] = pack(vector)
            embedded_now += len(batch)
            logging.info("embedded %d/%d", embedded_now, len(missing))
        timings["embed_s"] = round(time.monotonic() - t2, 1)
        (out_dir / "embeddings.json.gz").write_bytes(gzip.compress(json.dumps(
            {"model": model, "prefix": DOC_PREFIX, "dims": len(unpack(next(iter(vectors.values())))) if vectors else 0,
             "vectors": vectors}).encode(), mtime=0))

    (out_dir / "chunks.json.gz").write_bytes(gzip.compress(json.dumps(chunks, ensure_ascii=False).encode(), mtime=0))
    stats = crawler.stats
    manifest = {
        "version": args.version,
        "sources": ["https://site.getnet.com.br (sitemaps + links)", "https://www.getnet.net/en", "https://www.getnet.net/pt"],
        "discovered_urls": len(stats.discovered),
        "sitemap_urls": stats.sitemap_urls,
        "downloaded_pages": len(pages),
        "rendered_with_js": len(rendered),
        "skipped": dict(Counter(reason.split(":")[0] for reason in stats.skipped.values())),
        "failed": dict(Counter(stats.failed.values())),
        "skipped_urls": stats.skipped,
        "failed_urls": stats.failed,
        "stopped_by": getattr(stats, "stopped_by", None),
        "unvisited_in_frontier": getattr(stats, "unvisited", 0),
        "max_pages": args.max_pages,
        "pages_by_section": dict(Counter(section_of(p["url"]) for p in pages).most_common()),
        "pages_by_language": dict(Counter(p["language"] for p in pages)),
        "boilerplate_blocks_removed": removed,
        "chunks": len(chunks),
        "characters": sum(len(c["content"]) for c in chunks),
        "chunks_new_vs_previous": len({c["content_hash"] for c in chunks} - old_hashes) if previous else len(chunks),
        "previous_version": previous.name if previous else None,
        "embedding_model": model, "embedded_this_run": embedded_now,
        "timings": timings,
        "pages_by_market": dict(Counter(page_market(p["url"]) for p in pages)),
        "pages": [{"url": p["url"], "title": p["title"], "language": p["language"], "market": page_market(p["url"]),
                   "rendered_js": bool(p.get("rendered_js")),
                   "chars": sum(len(t) for _, t in p["blocks"])} for p in pages],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k not in {"pages", "skipped_urls", "failed_urls"}},
                     ensure_ascii=False, indent=2))
    return 0 if chunks else 2


if __name__ == "__main__":
    raise SystemExit(main())
