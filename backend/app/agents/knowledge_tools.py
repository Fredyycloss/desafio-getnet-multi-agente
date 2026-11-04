"""Tools of the Knowledge Agent (chosen by the LLM through function calling).

search_getnet_knowledge  RAG over the versioned official-site snapshot
search_getnet_site_live  live read of official pages (allowlist) chosen from the snapshot's URL inventory
web_search               public web (stable providers, see web_search_tool)
get_weather_forecast     Open-Meteo
get_exchange_rate        Frankfurter
"""
from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from ..language import normalize

logger = logging.getLogger(__name__)

KNOWLEDGE_TOOLS = [
    {"type": "function", "function": {"name": "search_getnet_knowledge",
        "description": "Search the indexed official Getnet websites (products, terminals, fees, Pix, receivables advance, "
                       "crediário, payment link, help-center articles). Use for any question about Getnet.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Standalone search query."}},
                       "required": ["query"]}}},
    {"type": "function", "function": {"name": "search_getnet_site_live",
        "description": "Read official Getnet pages live, only if the indexed knowledge does not contain the answer.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "web_search",
        "description": "Search the public web for general questions that are not about Getnet.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_weather_forecast",
        "description": "Weather forecast for a city.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}, "day": {"type": "string", "description": "today, tomorrow or YYYY-MM-DD"}},
            "required": ["city"]}}},
    {"type": "function", "function": {"name": "get_exchange_rate",
        "description": "Latest reference exchange rate between two currencies (ISO codes).",
        "parameters": {"type": "object", "properties": {
            "base": {"type": "string", "description": "e.g. EUR"}, "quote": {"type": "string", "description": "e.g. BRL"}},
            "required": ["base"]}}},
]
KNOWLEDGE_TOOL_NAMES = {t["function"]["name"] for t in KNOWLEDGE_TOOLS}
TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in TOKEN.findall(normalize(text)) if len(t) > 2}


def keyword_tool_choice(question: str) -> tuple[str, dict]:
    """Fallback only (no model / model unavailable): pick a tool by keywords."""
    text = normalize(question)
    if any(w in text for w in ("weather", "forecast", "clima", "previsao do tempo", "temperatura", "chover", "chuva")):
        return "get_weather_forecast", {}
    if any(w in text for w in ("exchange rate", "currency", "cambio", "cotacao", "dolar", "euro", "libra")):
        return "get_exchange_rate", {}
    return "search_getnet_knowledge", {"query": question}


def site_live_search(query: str, documents: list[dict], language: str, *, timeout: float = 8.0, pages: int = 2) -> list[dict]:
    """Rank official URLs of the snapshot inventory by title/section/URL match, fetch the best
    pages live (allowlist only) and return the passages that mention the query terms."""
    from ..knowledge.crawler import USER_AGENT, allowed, extract_page
    q = _tokens(query)
    if not q:
        return []
    candidates: dict[str, float] = {}
    for doc in documents:
        if doc.get("language", "pt") not in {language, "both"}:
            continue
        url = doc.get("url", "")
        overlap = len(q & _tokens(" ".join([doc.get("title", ""), doc.get("section", ""), url.replace("-", " ").replace("/", " ")])))
        if overlap:
            candidates[url] = max(candidates.get(url, 0), overlap)
    evidence: list[dict] = []
    for url, _ in sorted(candidates.items(), key=lambda item: -item[1])[:pages]:
        if not allowed(url):
            continue
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                continue
            page = extract_page(BeautifulSoup(response.content, "html.parser"), url)
        except requests.RequestException as exc:
            logger.warning("site_live_fetch_failed url=%s error=%s", url, type(exc).__name__)
            continue
        # Same spirit as the RAG threshold: a passage must cover at least half of the query terms.
        needed = max(2, (len(q) + 1) // 2)
        scored = sorted(((len(q & _tokens(text)), text) for _, text in page["blocks"]), key=lambda item: -item[0])
        passage = " ".join(text for score, text in scored[:6] if score >= needed)
        if passage:
            evidence.append({"title": page["title"], "url": url, "section": "live", "content": passage[:1500],
                             "score": 0.5, "source_type": "official_live_read"})
    return evidence
