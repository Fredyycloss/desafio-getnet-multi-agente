from __future__ import annotations
import json, logging, os, re
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks, start = [], 0
    while start < len(words):
        end = min(len(words), start + size // 5)
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = max(start + 1, end - overlap // 5)
    return chunks


def load_documents() -> list[dict]:
    docs: list[dict] = []
    try:
        docs.extend(json.loads((ROOT / "corpus.json").read_text(encoding="utf-8")))
    except Exception as exc:
        logger.exception("Falha ao carregar corpus local: %s", exc)
    urls = [u.strip() for u in os.getenv("KNOWLEDGE_URLS", "https://www.getnet.net/,https://www.getnet.net/en").split(",") if u.strip()]
    timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "8"))
    for url in urls:
        try:
            parsed = urlparse(url)
            if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() not in {"www.getnet.net", "getnet.net"}:
                logger.warning("URL de conhecimento ignorada por domínio não permitido: %s", url)
                continue
            response = requests.get(url, timeout=timeout, headers={"User-Agent": "GetnetAssistKnowledgeBot/1.0"})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for node in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
                node.decompose()
            content = clean_text(soup.get_text(" ", strip=True))
            if len(content) > 180:
                docs.append({"title": clean_text(soup.title.get_text()) if soup.title else "Site oficial Getnet", "url": url, "content": content[:24000]})
        except Exception as exc:
            logger.info("Ingestão externa não disponível para %s: %s", url, type(exc).__name__)
    chunks = []
    for doc in docs:
        for i, chunk in enumerate(chunk_text(doc.get("content", ""))):
            chunks.append({"title": doc.get("title", "Base de conhecimento"), "url": doc.get("url", "https://www.getnet.net/"), "content": chunk, "chunk_id": i})
    return chunks
