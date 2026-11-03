"""Ollama adapter (default, local, open-weight models, no API key)."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

from ...observability import record_model_usage, stage
from .base import LLMProvider, LLMTimeout, LLMUnavailable, call_timeout, normalised_response

logger = logging.getLogger(__name__)


def _ns_to_ms(value: Any) -> float | None:
    return round(value / 1_000_000, 2) if isinstance(value, (int, float)) else None


def _normalise_tool_calls(raw: list | None) -> list[dict]:
    calls = []
    for index, call in enumerate(raw or []):
        function = (call or {}).get("function", {}) or {}
        args = function.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": call.get("id") or f"call_{index}",
                      "function": {"name": str(function.get("name") or ""), "arguments": args if isinstance(args, dict) else {}}})
    return calls


class OllamaProvider(LLMProvider):
    """Chat with tool calling and embeddings through the Ollama HTTP API."""
    provider = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None, embedding_model: str | None = None):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
        self.embedding_model = embedding_model or os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self.timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
        # Keep both models resident between requests; reloading costs seconds on CPU.
        self.keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
        # Qwen3 "thinks" by default; hidden reasoning dominates CPU latency, so it is off.
        self.think_default = os.getenv("OLLAMA_THINK", "false").lower() == "true"
        # Local CPU profile: measured p95 of a full turn plus margin (see README).
        self.default_budget_seconds = float(os.getenv("LOCAL_LLM_BUDGET_SECONDS", "150"))

    # Kept for callers that used the old client API.
    def _call_timeout(self, purpose: str) -> float:
        return call_timeout(self.timeout, purpose)

    @staticmethod
    def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wire = []
        for item in messages:
            entry = {k: v for k, v in item.items() if k in {"role", "content", "tool_calls", "tool_name", "images"}}
            if entry.get("tool_calls"):
                entry["tool_calls"] = [{"function": c.get("function", {})} for c in entry["tool_calls"]]
            elif "tool_calls" in entry:
                entry.pop("tool_calls")
            wire.append(entry)
        return wire

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None,
             temperature=0.0, max_tokens=None, purpose="chat") -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._wire_messages(messages),
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": int(os.getenv("OLLAMA_CONTEXT_LENGTH", "4096")),
                "num_predict": max_tokens or int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "256")),
            },
        }
        num_thread = os.getenv("OLLAMA_NUM_THREAD", "").strip()
        if num_thread.isdigit():
            payload["options"]["num_thread"] = int(num_thread)
        if tools:
            payload["tools"] = tools
        payload["think"] = self.think_default if think is None else think
        if json_schema is not None:
            payload["format"] = json_schema
        elif json_mode:
            payload["format"] = "json"
        timeout = call_timeout(self.timeout, purpose)
        started = time.perf_counter()
        try:
            with stage(f"ollama_chat:{purpose}", "model"):
                response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
                response.raise_for_status()
                data = response.json()
                message = data.get("message")
                if not isinstance(message, dict):
                    raise LLMUnavailable("Ollama returned no assistant message")
                latency_ms = (time.perf_counter() - started) * 1000
                record_model_usage(
                    purpose=purpose, provider=self.provider, model=self.model,
                    prompt_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"),
                    load_ms=_ns_to_ms(data.get("load_duration")), prompt_ms=_ns_to_ms(data.get("prompt_eval_duration")),
                    generation_ms=_ns_to_ms(data.get("eval_duration")), latency_ms=round(latency_ms, 2), cost_usd=0.0,
                )
        except requests.Timeout as exc:
            raise LLMTimeout(f"Ollama chat timed out ({purpose}, {timeout:.0f}s)") from exc
        except (requests.RequestException, ValueError, LLMUnavailable) as exc:
            raise LLMUnavailable(f"Ollama chat failed: {type(exc).__name__}") from exc
        return normalised_response(
            content=str(message.get("content") or ""), tool_calls=_normalise_tool_calls(message.get("tool_calls")),
            provider=self.provider, model=self.model, prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"), latency_ms=latency_ms, cost_usd=0.0,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        timeout = call_timeout(self.timeout, "embed")
        try:
            with stage("ollama_embed", "model"):
                response = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.embedding_model, "input": texts, "keep_alive": self.keep_alive},
                    timeout=timeout,
                )
            response.raise_for_status()
            vectors = response.json().get("embeddings", [])
            if len(vectors) != len(texts):
                raise LLMUnavailable("Ollama returned an unexpected number of embeddings")
            return vectors
        except requests.Timeout as exc:
            raise LLMTimeout(f"Ollama embeddings timed out ({timeout:.0f}s)") from exc
        except (requests.RequestException, ValueError, LLMUnavailable) as exc:
            raise LLMUnavailable(f"Ollama embeddings failed: {type(exc).__name__}") from exc

    def health(self) -> dict:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            response.raise_for_status()
            names = [item.get("name", "") for item in response.json().get("models", [])]
            loaded = {self._with_default_tag(name) for name in names}
            return {
                "available": True,
                "chat_model_loaded": self._with_default_tag(self.model) in loaded,
                "embedding_model_loaded": self._with_default_tag(self.embedding_model) in loaded,
                "models": names,
            }
        except requests.RequestException:
            return {"available": False, "chat_model_loaded": False, "embedding_model_loaded": False, "models": []}

    @staticmethod
    def _with_default_tag(name: str) -> str:
        repository, separator, tag = name.rpartition(":")
        if separator and "/" not in tag:
            return name
        return f"{name}:latest"
