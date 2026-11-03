"""Single LLM provider layer used by every agent (see base.py for the contract)."""
from __future__ import annotations

import logging
import os

from .base import LLMBudgetExceeded, LLMProvider, LLMTimeout, LLMUnavailable, call_timeout

logger = logging.getLogger(__name__)

__all__ = ["LLMProvider", "LLMUnavailable", "LLMTimeout", "LLMBudgetExceeded", "call_timeout",
           "create_llm", "resolve_provider_name"]


def resolve_provider_name() -> str | None:
    """LLM_PROVIDER=auto|ollama|anthropic|none. auto: key present -> anthropic, else ollama
    when OLLAMA_ENABLED=true, else no model (deterministic fallback mode)."""
    from .anthropic_provider import anthropic_key_configured
    choice = os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto"
    ollama_enabled = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
    if choice == "none":
        return None
    if choice == "fixture":  # deterministic browser-test provider, never selected by auto
        return "fixture"
    if choice == "anthropic":
        return "anthropic" if anthropic_key_configured() else None
    if choice == "ollama":
        return "ollama"
    if anthropic_key_configured():
        return "anthropic"
    return "ollama" if ollama_enabled else None


def create_llm() -> LLMProvider | None:
    from .ollama import OllamaProvider
    name = resolve_provider_name()
    if name == "fixture":
        from .fixture import FixtureProvider
        return FixtureProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        # Embeddings are always the local nomic model.
        return AnthropicProvider(embedder=OllamaProvider())
    if name == "ollama":
        return OllamaProvider()
    if os.getenv("LLM_PROVIDER", "auto").strip().lower() == "anthropic":
        logger.warning("llm_provider_unconfigured provider=anthropic reason=missing_key")
    return None
