"""Public web search with stable providers (no HTML scraping).

Order: optional Brave Search API (WEB_SEARCH_API_KEY) → Wikipedia REST search + page
summary (pt/en) → DuckDuckGo Instant Answer API. Results always carry the source URL;
when every provider fails the caller reports "provider unavailable" and invents nothing.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)
USER_AGENT = "Mozilla/5.0 (compatible; GetnetAssistResearch/3.0)"


def _timeout() -> float:
    return max(1.0, min(float(os.getenv("REQUEST_TIMEOUT_SECONDS", "6")), 10.0))


def _brave(query: str, language: str, limit: int) -> list[dict]:
    key = os.getenv("WEB_SEARCH_API_KEY", "").strip()
    if not key:
        return []
    response = requests.get("https://api.search.brave.com/res/v1/web/search",
                            params={"q": query[:400], "count": limit, "search_lang": "en" if language == "en" else "pt-br"},
                            headers={"X-Subscription-Token": key, "Accept": "application/json", "User-Agent": USER_AGENT},
                            timeout=_timeout())
    response.raise_for_status()
    return [{"title": r.get("title", "")[:200], "url": r.get("url", ""), "snippet": r.get("description", "")[:450],
             "provider": "brave_search_api"} for r in (response.json().get("web", {}).get("results") or [])[:limit]
            if str(r.get("url", "")).startswith("https://")]


def _wikipedia(query: str, language: str, limit: int) -> list[dict]:
    lang = "en" if language == "en" else "pt"
    response = requests.get(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page", params={"q": query[:300], "limit": limit},
                            headers={"User-Agent": USER_AGENT}, timeout=_timeout())
    response.raise_for_status()
    results = []
    for page in response.json().get("pages", [])[:limit]:
        title = page.get("title", "")
        summary = ""
        try:
            detail = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}",
                                  headers={"User-Agent": USER_AGENT}, timeout=_timeout())
            if detail.ok:
                summary = detail.json().get("extract", "")
        except requests.RequestException:
            pass
        results.append({"title": title, "url": f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                        "snippet": (summary or page.get("excerpt", "") or page.get("description", ""))[:600],
                        "provider": "wikipedia_rest"})
    return results


def _duckduckgo_instant(query: str, language: str, limit: int) -> list[dict]:
    response = requests.get("https://api.duckduckgo.com/", params={"q": query[:300], "format": "json", "no_html": 1, "skip_disambig": 1},
                            headers={"User-Agent": USER_AGENT}, timeout=_timeout())
    if response.status_code != 200:
        return []
    data = response.json()
    results = []
    if data.get("AbstractText") and data.get("AbstractURL"):
        results.append({"title": data.get("Heading", query)[:200], "url": data["AbstractURL"], "snippet": data["AbstractText"][:600],
                        "provider": "duckduckgo_instant_answer"})
    for topic in data.get("RelatedTopics", []):
        if len(results) >= limit:
            break
        if topic.get("FirstURL") and topic.get("Text"):
            results.append({"title": topic["Text"][:120], "url": topic["FirstURL"], "snippet": topic["Text"][:450],
                            "provider": "duckduckgo_instant_answer"})
    return results


def search_web(query: str, language: str = "pt", max_results: int = 3) -> dict:
    """Returns {"ok", "provider", "results": [{title,url,snippet,provider}], "errors"}; never raises."""
    errors: dict[str, str] = {}
    for name, provider in (("brave", _brave), ("wikipedia", _wikipedia), ("duckduckgo_instant", _duckduckgo_instant)):
        try:
            results = [r for r in provider(query, language, max_results) if r.get("url")]
        except (requests.RequestException, ValueError, KeyError) as exc:
            errors[name] = type(exc).__name__
            logger.warning("web_search_provider_failed provider=%s error=%s", name, type(exc).__name__)
            continue
        if results:
            return {"ok": True, "provider": results[0]["provider"], "results": results, "errors": errors}
    return {"ok": False, "provider": None, "results": [], "errors": errors}
