"""Cloud provider with an offline fallback (LLM_FALLBACK_PROVIDER=ollama).

Only a key/credit failure (LLMAuthError) switches to the fallback; timeouts and other
errors keep the normal degraded handling. After the switch every call goes to the
fallback, the request budget switches to its profile, and responses show it in the trace.
"""
from __future__ import annotations

import logging

from ...observability import set_default_llm_budget
from .base import LLMAuthError, LLMProvider

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback
        self.fallback_active = False
        self.fallback_reason: str | None = None

    @property
    def active(self) -> LLMProvider:
        return self.fallback if self.fallback_active else self.primary

    @property
    def provider(self) -> str:  # type: ignore[override]
        return self.active.provider

    @property
    def model(self) -> str:  # type: ignore[override]
        return self.active.model

    @property
    def embedding_model(self) -> str:  # type: ignore[override]
        return self.primary.embedding_model or self.fallback.embedding_model

    @property
    def default_budget_seconds(self) -> float:  # type: ignore[override]
        return self.active.default_budget_seconds

    @property
    def key_failure_reason(self) -> str | None:
        # Answers produced by the fallback are not degraded by the key failure.
        return None if self.fallback_active else getattr(self.primary, "key_failure_reason", None)

    def switch(self, reason: str) -> None:
        if not self.fallback_active:
            self.fallback_active, self.fallback_reason = True, reason
            set_default_llm_budget(self.fallback.default_budget_seconds)
            logger.warning("llm_fallback_activated from=%s to=%s reason=%s", self.primary.provider, self.fallback.provider, reason)

    def check_key(self) -> str:
        state = self.primary.check_key() if hasattr(self.primary, "check_key") else "ok"
        if state.startswith("llm_"):
            self.switch(state)
        return state

    def chat(self, messages, tools=None, **kwargs) -> dict:
        if not self.fallback_active:
            try:
                return self.primary.chat(messages, tools, **kwargs)
            except LLMAuthError as exc:
                self.switch(exc.reason)
        return self.fallback.chat(messages, tools, **kwargs)

    def embed(self, texts):
        return self.primary.embed(texts)

    def health(self) -> dict:
        health = self.active.health()
        primary = self.primary.cloud_status() if hasattr(self.primary, "cloud_status") else {}
        return {**health, **primary, "fallback_provider": self.fallback.provider, "fallback_active": self.fallback_active,
                "fallback_reason": self.fallback_reason}

    def describe(self) -> dict:
        return {**self.active.describe(), "primary": self.primary.describe(), "fallback": self.fallback.describe(),
                "fallback_active": self.fallback_active, "fallback_reason": self.fallback_reason}
