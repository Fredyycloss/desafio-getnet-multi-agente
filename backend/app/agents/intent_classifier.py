"""Embedding kNN intent classifier for the hybrid Context Intelligence.

Labelled examples (intent_examples.json, written from scratch) are embedded once
with the local nomic-embed-text model and cached in SQLite. A message is
classified by cosine similarity to its k nearest examples. The hybrid mode uses
this result only for clear, low-risk turns and calls the LLM otherwise
(see ContextIntelligence.needs_llm).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from ..infra.llm import LLMProvider

EXAMPLES_PATH = Path(__file__).with_name("intent_examples.json")
# nomic-embed-text task prefix for classification.
PREFIX = "classification: "


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class EmbeddingIntentClassifier:
    def __init__(self, embedder: LLMProvider, db=None, *, k: int | None = None):
        self.embedder = embedder
        self.db = db
        self.k = k or int(os.getenv("CONTEXT_EMBEDDING_K", "5"))
        data = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))["intents"]
        self.agents = {intent: spec.get("agent") for intent, spec in data.items()}
        self.examples = [(intent, text) for intent, spec in data.items() for text in spec["examples"]]
        self._vectors: list[list[float]] | None = None

    def _cache_key(self, text: str) -> str:
        return "intent-example:" + hashlib.sha256((PREFIX + text).encode("utf-8")).hexdigest()

    def _ensure_vectors(self) -> list[list[float]]:
        if self._vectors is not None:
            return self._vectors
        model = getattr(self.embedder, "embedding_model", "")
        vectors: list[list[float] | None] = [
            self.db.get_embedding(self._cache_key(text), model) if self.db else None for _, text in self.examples]
        missing = [i for i, v in enumerate(vectors) if v is None]
        if missing:
            computed = self.embedder.embed([PREFIX + self.examples[i][1] for i in missing])
            for i, vector in zip(missing, computed):
                vectors[i] = vector
                if self.db:
                    self.db.save_embedding(self._cache_key(self.examples[i][1]), model, vector)
        self._vectors = [v for v in vectors if v is not None]
        return self._vectors

    def classify(self, message: str) -> dict:
        """Returns intent, agent, confidence (vote share of the top intent among the k
        neighbours, similarity-weighted), margin to the second intent and top similarity."""
        vectors = self._ensure_vectors()
        query = self.embedder.embed([PREFIX + message[:600]])[0]
        scored = sorted(((_cosine(query, v), self.examples[i][0]) for i, v in enumerate(vectors)), reverse=True)[:self.k]
        votes: dict[str, float] = {}
        for similarity, intent in scored:
            votes[intent] = votes.get(intent, 0.0) + max(similarity, 0.0)
        total = sum(votes.values()) or 1.0
        ranked = sorted(votes.items(), key=lambda item: item[1], reverse=True)
        top_intent, top_votes = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        return {
            "intent": top_intent,
            "agent": self.agents.get(top_intent),
            "confidence": round(top_votes / total, 4),
            "margin": round((top_votes - second) / total, 4),
            "top_similarity": round(scored[0][0], 4) if scored else 0.0,
        }
