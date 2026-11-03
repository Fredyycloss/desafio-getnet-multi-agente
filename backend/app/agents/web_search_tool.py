"""Best-effort public web search adapter for general/current-data questions.

Uses DuckDuckGo's HTML results endpoint without an API key. Search snippets are
untrusted and potentially incomplete, so this tool returns source links and
short snippets rather than asserting that a snippet is verified truth.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, urlparse, unquote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
SEARCH_URL = "https://html.duckduckgo.com/html/"


def _result_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        values = parse_qs(parsed.query)
        target = values.get("uddg", [None])[0]
        if target:
            href = unquote(target)
    if not href.startswith(("https://", "http://")):
        return None
    final = urlparse(href)
    if not final.hostname:
        return None
    return final._replace(fragment="").geturl()


def search_web(query: str, language: str = "pt", max_results: int = 3) -> dict:
    """Search the public web and return normalized results; fails closed on errors."""
    timeout = max(1.0, min(float(os.getenv("REQUEST_TIMEOUT_SECONDS", "4")), 8.0))
    locale = "us-en" if language == "en" else "br-pt"
    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": query[:400], "kl": locale},
            headers={"User-Agent": "Mozilla/5.0 (compatible; GetnetAssistDemo/1.2; educational project)"},
            timeout=timeout,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict] = []
        seen: set[str] = set()
        for result in soup.select(".result"):
            title_node = result.select_one(".result__title a")
            snippet_node = result.select_one(".result__snippet")
            if not title_node:
                continue
            url = _result_url(title_node.get("href", ""))
            title = " ".join(title_node.get_text(" ", strip=True).split())
            snippet = " ".join(snippet_node.get_text(" ", strip=True).split()) if snippet_node else ""
            if not url or not title or url in seen:
                continue
            seen.add(url)
            results.append({"title": title[:240], "url": url, "snippet": snippet[:500]})
            if len(results) >= max(1, min(max_results, 5)):
                break
        return {"query": query, "provider": "DuckDuckGo HTML", "results": results, "available": bool(results)}
    except Exception as exc:
        logger.info("Web search unavailable error=%s", type(exc).__name__)
        return {"query": query, "provider": "DuckDuckGo HTML", "results": [], "available": False}
