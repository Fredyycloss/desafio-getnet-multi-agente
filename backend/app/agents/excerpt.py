"""Focus a long text on the part that matters for a given text (question or answer).

Chunks average ~1,700 characters but prompts carry only a few hundred per evidence item, so
cutting at the start drops facts that sit later in the chunk. This picks, among windows that
start at sentence boundaries, the one covering the most distinct terms of the focus text.
"""
from __future__ import annotations

import re

from ..language import normalize

_TERM = re.compile(r"[a-z0-9]+")
_SENTENCE_START = re.compile(r"(?<=[.!?:;])\s+")


def _terms(text: str) -> set[str]:
    return {t for t in _TERM.findall(normalize(text)) if len(t) > 3 or t.isdigit()}


def focused_excerpt(text: str, focus: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    wanted = _terms(focus)
    if not wanted:
        return text[:limit]
    starts = [0] + [m.end() for m in _SENTENCE_START.finditer(text)]
    best_start, best_score = 0, (-1, False)
    for i, start in enumerate(starts):
        if start >= len(text):
            break
        first_sentence = text[start:starts[i + 1]] if i + 1 < len(starts) else text[start:]
        # Most distinct terms first; on a tie, prefer a window that opens on a matching
        # sentence, so the match is not cut at the window's end. Remaining ties keep the earliest.
        score = (len(wanted & _terms(text[start:start + limit])), bool(wanted & _terms(first_sentence)))
        if score > best_score:
            best_start, best_score = start, score
    window = text[best_start:best_start + limit]
    return ("… " if best_start else "") + window
