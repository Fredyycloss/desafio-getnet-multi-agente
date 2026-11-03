"""Provider-neutral LLM contract shared by every agent.

``LLMProvider.chat(messages, tools, json_schema, max_tokens, temperature, purpose)``
returns a normalised dict::

    {"content": str, "tool_calls": [{"id", "function": {"name", "arguments": dict}}],
     "message": {"role": "assistant", "content", "tool_calls"},   # appendable to messages
     "usage": {"prompt_tokens", "output_tokens", "latency_ms", "cost_usd"},
     "provider": str, "model": str}

Messages use OpenAI/Ollama-style roles (system/user/assistant/tool). Tools use the
``{"type": "function", "function": {name, description, parameters}}`` schema.
Every call is bounded by the request-wide LLM budget (``REQUEST_LLM_BUDGET_SECONDS``).
"""
from __future__ import annotations

import logging
from typing import Any

from ...observability import llm_time_remaining

logger = logging.getLogger(__name__)

# Below this many seconds of request budget a model call cannot finish.
MIN_CALL_SECONDS = 2.0


class LLMUnavailable(RuntimeError):
    """The provider failed, returned an unusable answer or is not configured."""


class LLMTimeout(LLMUnavailable):
    """A model call exceeded its per-call timeout or the request LLM budget."""


class LLMBudgetExceeded(LLMTimeout):
    """The request-wide LLM budget is exhausted."""


class LLMAuthError(LLMUnavailable):
    """The provider refused the credentials: key rejected (401), forbidden (403) or no credit.

    ``reason`` is one of llm_key_rejected, llm_key_forbidden, llm_no_credit. Never holds the key.
    """

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def call_timeout(per_call_seconds: float, purpose: str) -> float:
    """Per-call timeout bounded by what is left of the request budget."""
    remaining = llm_time_remaining()
    if remaining is None:
        return per_call_seconds
    if remaining < MIN_CALL_SECONDS:
        logger.warning("llm_budget_exhausted purpose=%s remaining_s=%.1f", purpose, remaining)
        raise LLMBudgetExceeded(f"LLM request budget exhausted before {purpose}")
    return min(per_call_seconds, remaining)


def normalised_response(*, content: str, tool_calls: list[dict], provider: str, model: str,
                        prompt_tokens: int | None, output_tokens: int | None, latency_ms: float,
                        cost_usd: float, extra_message: dict | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    if extra_message:
        message.update(extra_message)
    return {
        "content": content,
        "tool_calls": tool_calls,
        "message": message,
        "usage": {"prompt_tokens": prompt_tokens, "output_tokens": output_tokens,
                  "latency_ms": round(latency_ms, 2), "cost_usd": round(cost_usd, 8)},
        "provider": provider,
        "model": model,
    }


class LLMProvider:
    """Base class. Subclasses implement ``chat``, ``embed`` and ``health``."""
    provider = "base"
    model = ""
    embedding_model = ""
    # Default request-wide LLM budget for this provider profile (seconds).
    default_budget_seconds = 90.0

    def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None, *,
             json_mode: bool = False, json_schema: dict | None = None, think: bool | None = None,
             temperature: float = 0.0, max_tokens: int | None = None, purpose: str = "chat") -> dict:
        raise NotImplementedError

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError

    def describe(self) -> dict:
        """Public, secret-free description for /api/health."""
        return {"provider": self.provider, "model": self.model, "embedding_model": self.embedding_model,
                "default_budget_seconds": self.default_budget_seconds}
