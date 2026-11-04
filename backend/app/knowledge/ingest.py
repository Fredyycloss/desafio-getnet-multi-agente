"""Offline-first Getnet knowledge ingestion.

The runtime loads committed corpus/snapshots only. Refreshing official websites is
an explicit command, bounded to an allowlist, and never blocks application boot.
"""
from __future__ import annotations

import json
import logging
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
ALLOWED_HOSTS = {"site.getnet.com.br", "www.getnet.net"}
TRACKING_KEYS = {"gclid", "gbraid", "wbraid", "gad_source", "gad_campaignid", "fbclid", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
DEFAULT_URLS = [
    "https://site.getnet.com.br/get-lite/", "https://site.getnet.com.br/taxas/",
    "https://site.getnet.com.br/crediario/", "https://site.getnet.com.br/link-de-pagamento/",
    "https://site.getnet.com.br/pix/", "https://site.getnet.com.br/get-ajuda/",
    "https://site.getnet.com.br/get-ajuda-maquininha/", "https://site.getnet.com.br/get-ajuda-erros-maquininha/",
    "https://site.getnet.com.br/get-ajuda-whatsapp-business/descontinuacao-whatsapp-business/",
    "https://site.getnet.com.br/get-ajuda-pix/como-habilitar-o-recebimento-de-vendas-via-pix-no-aplicativo-getnet-brasil/",
    "https://site.getnet.com.br/get-ajuda-antecipacao-de-venda/como-antecipar-sua-vendas-pelo-app/",
    "https://site.getnet.com.br/get-ajuda-configuracoes/funcionalidades-portal-minha-conta-e-app-getnet-brasil/",
    "https://www.getnet.net/pt/", "https://www.getnet.net/en/",
]


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING_KEYS and not k.lower().startswith("utm_")]
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), (parsed.hostname or "").lower(), path, "", urlencode(query), ""))


def allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS and not parsed.username and not parsed.password


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def chunk_text(text: str, size: int = 1100, overlap: int = 150) -> list[str]:
    words = clean_text(text).split()
    if not words: return []
    chunks = []
    start = 0
    while start < len(words):
        end = min(len(words), start + size)
        chunk = " ".join(words[start:end])
        if len(chunk) >= 80: chunks.append(chunk)
        if end >= len(words): break
        start = max(start + 1, end - overlap)
    return chunks


def _page_language(url: str, content: str) -> str:
    path = urlparse(url).path.lower()
    if "/en/" in path: return "en"
    if urlparse(url).hostname == "site.getnet.com.br": return "pt"
    words = set(re.findall(r"[a-z]+", content[:3000].lower()))
    return "en" if len(words & {"the", "and", "with", "payment", "your", "business"}) > len(words & {"que", "para", "com", "vendas", "pagamento"}) else "pt"


def fetch_page(url: str, timeout: float = 8.0) -> tuple[dict | None, list[str]]:
    canonical = canonicalize_url(url)
    if not allowed_url(canonical): return None, []
    try:
        response = requests.get(canonical, timeout=timeout, headers={"User-Agent": "GetnetAssistKnowledgeIndexer/2.0 (educational; contact: repository-maintainer)"}, allow_redirects=True)
        response.raise_for_status()
        if len(response.content) > 4_000_000 or "html" not in response.headers.get("content-type", "text/html").lower(): return None, []
        final_url = canonicalize_url(response.url)
        if not allowed_url(final_url): return None, []
        soup = BeautifulSoup(response.text, "html.parser")
        links = []
        for anchor in soup.find_all("a", href=True):
            candidate = canonicalize_url(urljoin(final_url, anchor["href"]))
            if allowed_url(candidate) and candidate not in links: links.append(candidate)
        for node in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form", "iframe"]): node.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        # Preserve headings as section boundaries for better chunk-level metadata.
        parts = []
        for node in main.find_all(["h1", "h2", "h3", "p", "li"]):
            value = clean_text(node.get_text(" ", strip=True))
            if value: parts.append(value)
        text = clean_text("\n".join(parts) if parts else main.get_text(" ", strip=True))
        if len(text) < 250: return None, links
        title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else "Getnet official page"
        return {"title": title, "url": final_url, "content": text[:50000], "language": _page_language(final_url, text),
                "source_type": "official_web_snapshot", "captured_at": datetime.now(timezone.utc).isoformat(),
                "content_hash": __import__("hashlib").sha256(text.encode()).hexdigest()}, links
    except Exception as exc:
        logger.warning("ingestion_failed url=%s error=%s", canonical, type(exc).__name__)
        return None, []


def crawl_official_site(seed_urls: list[str] | None = None, max_pages: int = 24, timeout: float = 8.0) -> list[dict]:
    queue = deque(canonicalize_url(x) for x in (seed_urls or DEFAULT_URLS) if allowed_url(x))
    visited: set[str] = set(); documents = []
    max_pages = max(1, min(max_pages, 40))
    while queue and len(visited) < max_pages:
        batch = []
        while queue and len(batch) < min(5, max_pages - len(visited)):
            url = queue.popleft()
            if url not in visited: visited.add(url); batch.append(url)
        if not batch: continue
        found = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_page, url, timeout) for url in batch]
            for future in as_completed(futures):
                doc, links = future.result()
                if doc: documents.append(doc)
                found.extend(links)
        found.sort(key=lambda x: (0 if any(term in urlparse(x).path for term in ("get-lite", "get-smart", "get-classica", "crediario", "link-de-pagamento", "taxas", "pix", "get-ajuda", "erros")) else 1, x))
        for link in found:
            if link not in visited and link not in queue: queue.append(link)
    return documents


SNAPSHOT_DIR = ROOT / "snapshots"
LEGACY_CURATED = ROOT / "corpus.json"


def latest_snapshot(exclude: str | None = None) -> Path | None:
    """Most recent snapshots/<version>/ with a chunks file (versions sort by date)."""
    if not SNAPSHOT_DIR.exists():
        return None
    versions = sorted(d for d in SNAPSHOT_DIR.iterdir() if d.is_dir() and (d / "chunks.json.gz").exists() and d.name != exclude)
    return versions[-1] if versions else None


def load_snapshot_vectors(snapshot: Path | None = None) -> tuple[str | None, str, dict[str, list[float]]]:
    """Precomputed document embeddings of a snapshot: (model, prefix, {content_hash: vector})."""
    import base64
    import gzip
    import struct
    snapshot = snapshot or latest_snapshot()
    path = snapshot / "embeddings.json.gz" if snapshot else None
    if not path or not path.exists():
        return None, "", {}
    data = json.loads(gzip.decompress(path.read_bytes()))
    vectors = {}
    for key, packed in data["vectors"].items():
        raw = base64.b64decode(packed)
        vectors[key] = list(struct.unpack(f"<{len(raw) // 2}e", raw))
    return data.get("model"), data.get("prefix", ""), vectors


def load_legacy_curated() -> list[dict]:
    """The 26 hand-written summaries used before the full-site snapshot (kept only as an
    evaluation baseline; not loaded at runtime)."""
    loaded = json.loads(LEGACY_CURATED.read_text(encoding="utf-8")) if LEGACY_CURATED.exists() else []
    out = []
    for doc in loaded:
        for idx, chunk in enumerate(chunk_text(doc.get("content", ""))):
            out.append({"title": doc.get("title", "Getnet"), "url": doc["url"], "section": doc.get("title", ""),
                        "content": chunk, "language": doc.get("language", "pt"), "chunk_id": f"legacy-{len(out)}",
                        "source_type": "curated_summary", "content_hash": None})
    return out


def load_documents() -> list[dict]:
    """Load the latest versioned official-site snapshot; never crawl at service startup.

    Falls back to the legacy curated summaries only when no snapshot exists.
    """
    import gzip
    snapshot = latest_snapshot()
    if snapshot is None:
        logger.warning("knowledge_snapshot_missing using=legacy_curated_summaries")
        return load_legacy_curated()
    try:
        chunks = json.loads(gzip.decompress((snapshot / "chunks.json.gz").read_bytes()))
    except (OSError, ValueError):
        logger.exception("knowledge_snapshot_read_failed version=%s", snapshot.name)
        return load_legacy_curated()
    for chunk in chunks:
        chunk["corpus_version"] = snapshot.name
    return [c for c in chunks if allowed_url(c.get("url", ""))]
