"""Single LLM provider layer used by every agent (see base.py for the contract)."""
from __future__ import annotations

import logging
import os

from .base import LLMAuthError, LLMBudgetExceeded, LLMProvider, LLMTimeout, LLMUnavailable, call_timeout

logger = logging.getLogger(__name__)

__all__ = ["LLMProvider", "LLMUnavailable", "LLMTimeout", "LLMBudgetExceeded", "LLMAuthError", "call_timeout",
           "create_llm", "resolve_provider_name"]


def resolve_provider_name() -> str | None:
    """LLM_PROVIDER=auto|ollama|anthropic|replay|none. auto: key present -> anthropic, else ollama
    when OLLAMA_ENABLED=true, else no model (deterministic fallback mode)."""
    from .anthropic_provider import anthropic_key_configured
    choice = os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto"
    ollama_enabled = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
    if choice == "none":
        return None
    if choice == "fixture":  # deterministic browser-test provider, never selected by auto
        return "fixture"
    if choice == "replay":  # recorded cloud calls (docs/evidence/cloud_runs), never selected by auto
        return "replay"
    if choice == "anthropic":
        return "anthropic" if anthropic_key_configured() else None
    if choice == "ollama":
        return "ollama"
    if anthropic_key_configured():
        return "anthropic"
    return "ollama" if ollama_enabled else None


def create_llm() -> LLMProvider | None:
    llm = _create_llm()
    record_dir = os.getenv("LLM_RECORD_DIR", "").strip()
    if llm is not None and record_dir and llm.provider != "replay":
        from .cassette import RecordingProvider
        logger.info("llm_recording dir=%s", record_dir)
        return RecordingProvider(llm, record_dir)
    return llm


def _create_llm() -> LLMProvider | None:
    from .ollama import OllamaProvider
    name = resolve_provider_name()
    if name == "replay":
        from .cassette import ReplayProvider
        return ReplayProvider(os.getenv("LLM_REPLAY_DIR", "").strip() or None)
    if name == "fixture":
        from .fixture import FixtureProvider
        return FixtureProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        # Embeddings are always the local nomic model.
        cloud = AnthropicProvider(embedder=OllamaProvider())
        if os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower() == "ollama":
            from .fallback import FallbackProvider
            return FallbackProvider(cloud, OllamaProvider())
        return cloud
    if name == "ollama":
        return OllamaProvider()
    if os.getenv("LLM_PROVIDER", "auto").strip().lower() == "anthropic":
        logger.warning("llm_provider_unconfigured provider=anthropic reason=missing_key")
    return None
