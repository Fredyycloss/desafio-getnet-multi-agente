"""Deterministic scripted provider for the browser test (LLM_PROVIDER=fixture only).

It never runs unless explicitly selected, reports itself as provider "fixture" in
/api/health, and exists so CI can drive the real UI and API without a model.
"""
from __future__ import annotations

import json
import time

from .base import LLMProvider, LLMUnavailable, normalised_response


class FixtureProvider(LLMProvider):
    provider = "fixture"
    model = "scripted-fixture"
    embedding_model = ""
    default_budget_seconds = 30.0

    @staticmethod
    def _assessment(message: str, selected: str | None) -> dict:
        text = message.casefold()
        base = {"intent": "product question", "risk_level": "safe", "ambiguity_level": "low",
                "figurative_language": False, "needs_clarification": False, "needs_human": False,
                "recommended_agents": ["knowledge_specialist"], "recommended_action": "route_to_agent",
                "recommended_destination": "knowledge_specialist", "confidence": 0.95,
                "operational_reason": "fixture routing"}
        if not selected and any(word in text for word in ("estranha", "estranho", "strange")):
            base.update(intent="unclear terminal issue", ambiguity_level="high", needs_clarification=True,
                        recommended_agents=["customer_support_specialist"], recommended_action="clarify",
                        recommended_destination="clarification", confidence=0.4)
        return base

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None,
             temperature=0.0, max_tokens=None, purpose="chat") -> dict:
        started = time.perf_counter()
        content = ""
        if purpose == "context_intelligence":
            payload = json.loads(messages[-1]["content"])
            content = json.dumps(self._assessment(payload.get("current_message", ""), payload.get("selected_option")))
        elif purpose == "critic":
            content = json.dumps({"approved": True, "issues": []})
        elif purpose == "knowledge":
            content = "Segundo o material oficial recuperado, a resposta está na fonte citada [1]."
        elif purpose.startswith("supervisor"):
            content = "FINAL"
        else:
            raise LLMUnavailable(f"fixture has no script for {purpose}")
        return normalised_response(content=content, tool_calls=[], provider=self.provider, model=self.model,
                                   prompt_tokens=0, output_tokens=0,
                                   latency_ms=(time.perf_counter() - started) * 1000, cost_usd=0.0)

    def embed(self, texts):
        raise LLMUnavailable("fixture provider has no embeddings (BM25 only)")

    def health(self) -> dict:
        return {"available": True, "chat_model_loaded": True, "embedding_model_loaded": False, "models": [self.model]}
