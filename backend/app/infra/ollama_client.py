"""Backward-compatible names. New code imports from ``app.infra.llm``."""
from .llm.base import MIN_CALL_SECONDS, LLMBudgetExceeded as OllamaBudgetExceeded  # noqa: F401
from .llm.base import LLMTimeout as OllamaTimeout, LLMUnavailable as OllamaUnavailable  # noqa: F401
from .llm.ollama import OllamaProvider as OllamaClient  # noqa: F401
