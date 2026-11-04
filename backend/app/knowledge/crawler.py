"""Whole-site crawler for the official Getnet websites (explicit refresh command only).

Discovery: robots.txt → sitemaps (and sub-sitemaps) → internal links. Politeness: robots
rules, ~1 s pause with jitter, retries with backoff, generic User-Agent, HTTPS + allowlist
only, HTML only. Extraction removes navigation/cookie/footer blocks and text repeated across
pages, splits by headings and records rich metadata. The runtime never crawls.
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .ingest import canonicalize_url

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; KnowledgeIndexer/3.0; +https://www.getnet.net/)"
ALLOWED_HOSTS = {"site.getnet.com.br", "www.getnet.net"}
# www.getnet.net serves several countries; the challenge points to /en and the Brazilian
# merchant audience reads /pt. Spanish-language country sites are out of scope.
GETNET_NET_PREFIXES = ("/en", "/pt")
SITEMAPS = [
    "https://site.getnet.com.br/sitemap_index.xml",
    "https://www.getnet.net/en/sitemap.xml",
    "https://www.getnet.net/pt/sitemap.xml",
]
SEEDS = [
    "https://site.getnet.com.br/", "https://site.getnet.com.br/get-ajuda/", "https://site.getnet.com.br/taxas/",
    "https://www.getnet.net/en/", "https://www.getnet.net/pt/",
    # Official pages not reachable from sitemaps/links (help centre, product pages): known entry points.
    "https://site.getnet.com.br/get-lite/", "https://site.getnet.com.br/get-ajuda-maquininha/",
    "https://site.getnet.com.br/get-ajuda-erros-maquininha/",
    "https://site.getnet.com.br/get-ajuda-whatsapp-business/descontinuacao-whatsapp-business/",
    "https://site.getnet.com.br/get-ajuda-pix/como-habilitar-o-recebimento-de-vendas-via-pix-no-aplicativo-getnet-brasil/",
    "https://site.getnet.com.br/get-ajuda-configuracoes/funcionalidades-portal-minha-conta-e-app-getnet-brasil/",
    "https://site.getnet.com.br/get-ajuda-link-de-pagamento/", "https://site.getnet.com.br/get-ajuda-pix/",
    "https://site.getnet.com.br/get-ajuda-recebimentos/", "https://site.getnet.com.br/get-ajuda-app-getnet/",
]
SKIP_PATH = re.compile(
    r"/(wp-admin|wp-content|wp-includes|wp-json|feed|tag|author|page/\d+|comments|xmlrpc|cdn-cgi|measures)(/|$)"
    r"|\.(png|jpe?g|gif|svg|webp|ico|css|js|json|xml|zip|mp4|mp3|woff2?|ttf|eot|pdf|docx?|xlsx?)$",
    re.IGNORECASE)
NOISE_ATTR = re.compile(r"cookie|consent|lgpd|newsletter|modal|popup|share|social|breadcrumb|navbar|offcanvas|skip-link",
                        re.IGNORECASE)
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "dt", "dd", "blockquote", "summary", "figcaption"]
HEADINGS = {"h1", "h2", "h3", "h4"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.query:
        return False
    if SKIP_PATH.search(parsed.path):
        return False
    if parsed.hostname == "www.getnet.net":
        return any(parsed.path == p or parsed.path.startswith(p + "/") for p in GETNET_NET_PREFIXES)
    return True


def page_market(url: str) -> str:
    """BR = Getnet Brasil; PT = Getnet Portugal (www.getnet.net/pt); global = www.getnet.net/en."""
    parsed = urlparse(url)
    if parsed.hostname == "site.getnet.com.br":
        return "BR"
    return "PT" if parsed.path == "/pt" or parsed.path.startswith("/pt/") else "global"


def page_language(url: str) -> str:
    path = urlparse(url).path
    return "en" if path == "/en" or path.startswith("/en/") else "pt"


@dataclass
class CrawlStats:
    discovered: set = field(default_factory=set)
    fetched: list = field(default_factory=list)
    skipped: dict = field(default_factory=dict)  # url -> reason
    failed: dict = field(default_factory=dict)   # url -> reason
    sitemap_urls: int = 0
    started: float = field(default_factory=time.monotonic)


class Crawler:
    def __init__(self, *, max_pages: int = 2000, pause: float = 1.0, timeout: float = 20.0, session=None):
        self.max_pages = max_pages
        self.pause = pause
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        self.robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.stats = CrawlStats()
        self._last = 0.0

    # -- politeness ---------------------------------------------------------------
    def _wait(self) -> None:
        delay = self.pause * random.uniform(0.8, 1.4) - (time.monotonic() - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def _get(self, url: str) -> requests.Response | None:
        for attempt in range(3):
            self._wait()
            try:
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return response
            except requests.RequestException as exc:
                if attempt == 2:
                    self.stats.failed[url] = type(exc).__name__
                    return None
                time.sleep(2 ** (attempt + 1))
        return None

    def robots_allows(self, url: str) -> bool:
        host = urlparse(url).hostname
        if host not in self.robots:
            parser = robotparser.RobotFileParser()
            response = self._get(f"https://{host}/robots.txt")
            if response is not None and response.status_code == 200 and "text/plain" in response.headers.get("content-type", ""):
                parser.parse(response.text.splitlines())
                self.robots[host] = parser
            else:  # no robots.txt (404/HTML): everything allowed
                self.robots[host] = None
        parser = self.robots[host]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    # -- discovery ------------------------------------------------------------------
    def sitemap_urls(self, url: str, depth: int = 0) -> list[str]:
        response = self._get(url)
        if response is None or response.status_code != 200 or "xml" not in response.headers.get("content-type", ""):
            self.stats.skipped[url] = f"sitemap_unavailable:{getattr(response, 'status_code', 'error')}"
            return []
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", response.text)
        if "<sitemapindex" in response.text and depth < 2:
            return [u for loc in locs for u in self.sitemap_urls(loc, depth + 1)]
        return locs

    # -- fetch + extraction ---------------------------------------------------------
    def fetch(self, url: str) -> tuple[dict | None, list[str]]:
        response = self._get(url)
        if response is None:
            return None, []
        if response.status_code != 200:
            self.stats.failed[url] = f"http_{response.status_code}"
            return None, []
        ctype = response.headers.get("content-type", "")
        if "html" not in ctype:
            self.stats.skipped[url] = f"not_html:{ctype.split(';')[0]}"
            return None, []
        final = canonicalize_url(response.url)
        if not allowed(final):
            self.stats.skipped[url] = "redirect_outside_allowlist"
            return None, []
        soup = BeautifulSoup(response.content, "html.parser")
        links = []
        for anchor in soup.find_all("a", href=True):
            candidate = canonicalize_url(urljoin(final, anchor["href"].split("#")[0]))
            if allowed(candidate):
                links.append(candidate)
        return extract_page(soup, final), links

    def crawl(self, *, seeds: list[str] | None = None, seen: set[str] | None = None,
              known_pages: set[str] | None = None, use_sitemaps: bool = True) -> list[dict]:
        """Full crawl, or an incremental one from ``seeds`` skipping ``seen`` URLs."""
        queue: deque[str] = deque()
        if use_sitemaps:
            for sitemap in SITEMAPS:
                for loc in self.sitemap_urls(sitemap):
                    canonical = canonicalize_url(loc)
                    if allowed(canonical):
                        queue.append(canonical)
                        self.stats.sitemap_urls += 1
        queue.extend(canonicalize_url(s) for s in (seeds if seeds is not None else SEEDS))
        seen = set(seen or ())
        final_urls: set[str] = set(known_pages or ())
        pages: list[dict] = []
        while queue and len(seen) < self.max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            self.stats.discovered.add(url)
            if not self.robots_allows(url):
                self.stats.skipped[url] = "robots_disallow"
                continue
            page, links = self.fetch(url)
            if page and page["url"] in final_urls:
                self.stats.skipped[url] = "duplicate_final_url"  # variant URL redirecting to a page we have
            elif page and page["blocks"]:
                final_urls.add(page["url"])
                pages.append(page)
                self.stats.fetched.append(url)
            elif page is not None:
                self.stats.skipped[url] = "no_text"
            for link in links:
                if link not in seen:
                    self.stats.discovered.add(link)
                    queue.append(link)
            if len(seen) % 25 == 0:
                logger.info("crawl_progress seen=%d pages=%d queue=%d", len(seen), len(pages), len(queue))
        self.stats.stopped_by = "max_pages" if queue else "frontier_exhausted"
        self.stats.unvisited = len({u for u in queue if u not in seen})
        return pages


def extract_page(soup: BeautifulSoup, url: str) -> dict:
    title = _clean(soup.title.get_text(" ")) if soup.title else url
    crumb_node = soup.find(attrs={"class": re.compile("breadcrumb", re.I)})
    breadcrumb = _clean(crumb_node.get_text(" > ")) if crumb_node else " > ".join(p for p in urlparse(url).path.split("/") if p)
    for node in soup(["script", "style", "noscript", "svg", "iframe", "form", "header", "footer", "nav", "aside", "button"]):
        node.decompose()
    for node in soup.find_all(True):
        attrs = " ".join([node.get("id") or "", *(node.get("class") or [])]) if node.attrs is not None else ""
        if attrs and NOISE_ATTR.search(attrs):
            node.decompose()
    body = soup.body or soup
    body_len = len(_clean(body.get_text(" "))) or 1
    main = body
    for candidate in (soup.find("main"), soup.find("article")):
        # A <main>/<article> is used only when it really holds the page copy (not a card).
        if candidate is not None and len(_clean(candidate.get_text(" "))) >= 0.4 * body_len:
            main = candidate
            break
    blocks: list[tuple[str, str]] = []  # (kind, text) kind = heading level or "text"
    taken: set[int] = set()
    for node in main.find_all(BLOCK_TAGS):
        if any(id(parent) in taken for parent in node.parents):
            continue
        text = _clean(node.get_text(" "))
        if not text:
            continue
        taken.add(id(node))
        blocks.append((node.name if node.name in HEADINGS else "text", text))
    full = _clean(main.get_text(" "))
    if sum(len(t) for _, t in blocks) < 0.5 * len(full):
        # Builder pages keep copy in bare <div>/<span>: fall back to visible lines.
        blocks = [("text", line) for line in (_clean(l) for l in main.get_text("\n").splitlines()) if len(line) > 2]
    return {"url": url, "title": title, "breadcrumb": breadcrumb[:200], "language": page_language(url),
            "market": page_market(url), "blocks": blocks,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def remove_boilerplate(pages: list[dict], min_share: float = 0.2, min_pages: int = 5) -> int:
    """Drop text blocks repeated on many pages of the same host (menus, footers, banners)."""
    removed = 0
    by_host: dict[str, list[dict]] = {}
    for page in pages:
        by_host.setdefault(urlparse(page["url"]).hostname, []).append(page)
    for host_pages in by_host.values():
        counts = Counter(text for page in host_pages for text in {t for _, t in page["blocks"]})
        limit = max(min_pages, int(min_share * len(host_pages)))
        common = {text for text, n in counts.items() if n >= limit}
        for page in host_pages:
            before = len(page["blocks"])
            page["blocks"] = [(k, t) for k, t in page["blocks"] if t not in common]
            removed += before - len(page["blocks"])
    return removed


def _norm_for_hash(text: str) -> str:
    return re.sub(r"[^a-z0-9à-ú]+", " ", text.casefold()).strip()


def chunk_pages(pages: list[dict], *, target_words: int = 350, max_words: int = 600, overlap: int = 50) -> list[dict]:
    """Heading-based chunks with metadata; short sections are merged, long ones split with overlap."""
    chunks: list[dict] = []
    seen_hashes: set[str] = set()
    for page in pages:
        sections: list[tuple[str, list[str]]] = []
        heading = page["title"]
        for kind, text in page["blocks"]:
            if kind in HEADINGS:
                heading = text[:160]
                sections.append((heading, []))
            else:
                if not sections:
                    sections.append((heading, []))
                sections[-1][1].append(text)
        merged: list[tuple[str, list[str]]] = []
        for section, texts in sections:
            words = sum(len(t.split()) for t in texts)
            if merged and sum(len(t.split()) for t in merged[-1][1]) + words <= target_words:
                merged[-1] = (merged[-1][0], merged[-1][1] + [f"{section}:"] + texts if texts else merged[-1][1])
            elif texts:
                merged.append((section, texts))
        for section, texts in merged:
            words = " ".join(texts).split()
            if len(words) < 25:
                continue
            start = 0
            while start < len(words):
                piece = " ".join(words[start:start + max_words])
                digest = hashlib.sha256(_norm_for_hash(piece).encode()).hexdigest()
                if digest not in seen_hashes:
                    seen_hashes.add(digest)
                    chunks.append({
                        "chunk_id": f"{digest[:16]}",
                        "url": page["url"], "title": page["title"], "section": section, "breadcrumb": page["breadcrumb"],
                        "language": page["language"], "market": page.get("market") or page_market(page["url"]),
                        "fetched_at": page["fetched_at"], "content_hash": digest,
                        "source_type": "official_web_snapshot", "content": piece,
                    })
                if start + max_words >= len(words):
                    break
                start += max_words - overlap
    return chunks
