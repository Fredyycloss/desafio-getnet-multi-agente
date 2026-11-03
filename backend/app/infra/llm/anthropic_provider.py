"""Anthropic adapter (optional cloud mode, Claude Haiku 5.5 by default).

The key is read only from ``GETNET_ANTHROPIC_API_KEY`` (never ``ANTHROPIC_API_KEY``),
passed explicitly to the SDK and never logged, traced, returned or stored.
Embeddings stay local: they are delegated to the Ollama ``nomic-embed-text`` model.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ...observability import record_model_usage, stage
from .base import LLMProvider, LLMTimeout, LLMUnavailable, call_timeout, normalised_response

logger = logging.getLogger(__name__)

KEY_ENV = "GETNET_ANTHROPIC_API_KEY"
# JSON-schema keywords outside the structured-output subset; values are validated by pydantic afterwards.
_UNSUPPORTED_SCHEMA_KEYS = {"title", "default", "maxLength", "minLength", "maximum", "minimum",
                            "maxItems", "minItems", "exclusiveMaximum", "exclusiveMinimum", "pattern"}


def anthropic_key_configured() -> bool:
    return bool(os.getenv(KEY_ENV, "").strip())


def strict_schema(schema: Any) -> Any:
    """Copy of a pydantic JSON schema reduced to the structured-output subset."""
    if isinstance(schema, dict):
        cleaned = {k: strict_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
        if cleaned.get("type") == "object":
            cleaned["additionalProperties"] = False
            cleaned.setdefault("required", list((cleaned.get("properties") or {}).keys()))
        return cleaned
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    return schema


def to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    converted = []
    for tool in tools or []:
        function = tool.get("function", tool)
        converted.append({
            "name": function["name"],
            "description": function.get("description", ""),
            "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
        })
    return converted


def to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict]]:
    """OpenAI/Ollama-style messages -> (system, Anthropic messages).

    Assistant tool calls become ``tool_use`` blocks; following ``tool`` messages become
    ``tool_result`` blocks matched in order. Tool calls that were never executed get an
    error result so the conversation stays valid. Consecutive same-role turns are merged.
    """
    system_parts: list[str] = []
    out: list[dict] = []
    pending: list[str] = []

    def push(role: str, blocks: list[dict]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    def close_pending() -> None:
        if pending:
            push("user", [{"type": "tool_result", "tool_use_id": tid, "content": "not executed", "is_error": True}
                          for tid in pending])
            pending.clear()

    for item in messages:
        role = item.get("role")
        content = str(item.get("content") or "")
        if role == "system":
            system_parts.append(content)
            continue
        if role == "tool":
            tool_id = pending.pop(0) if pending else None
            if tool_id is None:
                push("user", [{"type": "text", "text": f"Tool observation: {content}"}])
            else:
                push("user", [{"type": "tool_result", "tool_use_id": tool_id, "content": content or "(empty)"}])
            continue
        close_pending()
        if role == "assistant":
            raw = item.get("provider_content")
            if raw:
                blocks = list(raw)
            else:
                blocks = [{"type": "text", "text": content}] if content else []
                for index, call in enumerate(item.get("tool_calls") or []):
                    function = call.get("function", {})
                    blocks.append({"type": "tool_use", "id": call.get("id") or f"toolu_{len(out)}_{index}",
                                   "name": function.get("name", ""), "input": function.get("arguments") or {}})
            pending.extend(b["id"] for b in blocks if b.get("type") == "tool_use")
            if blocks:
                push("assistant", blocks)
        else:
            push("user", [{"type": "text", "text": content or "(empty)"}])
    close_pending()
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(conversation start)"}]})
    return "\n\n".join(p for p in system_parts if p), out


class AnthropicProvider(LLMProvider):
    provider = "anthropic"

    def __init__(self, *, client: Any = None, embedder: LLMProvider | None = None):
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
        self.timeout = float(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "20"))
        self.max_retries = int(os.getenv("ANTHROPIC_MAX_RETRIES", "1"))
        # Haiku 5.5 thinks by default and thinking counts toward max_tokens; agent caps
        # were sized for a slow CPU, so a floor leaves room for the visible answer.
        self.min_output_tokens = int(os.getenv("ANTHROPIC_MIN_OUTPUT_TOKENS", "1024"))
        self.thinking = os.getenv("ANTHROPIC_THINKING", "disabled").strip().lower()
        self.effort = os.getenv("ANTHROPIC_EFFORT", "low").strip().lower()
        self.input_usd_per_mtok = float(os.getenv("ANTHROPIC_INPUT_USD_PER_MTOK", "0.10"))
        self.output_usd_per_mtok = float(os.getenv("ANTHROPIC_OUTPUT_USD_PER_MTOK", "0.50"))
        self.default_budget_seconds = float(os.getenv("CLOUD_LLM_BUDGET_SECONDS", "30"))
        self.embedder = embedder
        self.embedding_model = getattr(embedder, "embedding_model", "") if embedder else ""
        if client is None:
            key = os.getenv(KEY_ENV, "").strip()
            if not key:
                raise LLMUnavailable(f"{KEY_ENV} is not set")
            import anthropic  # imported lazily: the offline mode never needs the SDK
            client = anthropic.Anthropic(api_key=key, timeout=self.timeout, max_retries=self.max_retries)
            del key
        self._client = client

    def __repr__(self) -> str:  # never expose the client (it holds the key)
        return f"AnthropicProvider(model={self.model!r})"

    def cost(self, prompt_tokens: int, output_tokens: int) -> float:
        return (prompt_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok) / 1_000_000

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None,
             temperature=0.0, max_tokens=None, purpose="chat") -> dict:
        system, wire = to_anthropic_messages(messages)
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max(int(max_tokens or 0), self.min_output_tokens),
            "messages": wire,
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = to_anthropic_tools(tools)
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": strict_schema(json_schema)}
        elif json_mode:
            params["system"] = (params.get("system", "") + "\n\nReturn one JSON object only.").strip()
        if output_config:
            params["output_config"] = output_config
        if think is True or self.thinking == "adaptive":
            params["thinking"] = {"type": "adaptive"}
        elif self.thinking == "disabled":
            params["thinking"] = {"type": "disabled"}
        # temperature is intentionally not sent: current models reject non-default sampling.
        timeout = call_timeout(self.timeout, purpose)
        started = time.perf_counter()
        try:
            import anthropic
            timeout_error, base_error = anthropic.APITimeoutError, anthropic.AnthropicError
        except ImportError:  # contract tests with an injected fake client
            timeout_error, base_error = TimeoutError, Exception
        try:
            with stage(f"anthropic_chat:{purpose}", "model"):
                response = self._client.messages.create(**params, timeout=timeout)
        except timeout_error as exc:
            raise LLMTimeout(f"Anthropic chat timed out ({purpose}, {timeout:.0f}s)") from exc
        except base_error as exc:
            status = getattr(exc, "status_code", None)
            logger.warning("anthropic_chat_failed purpose=%s error_type=%s status=%s", purpose, type(exc).__name__, status)
            raise LLMUnavailable(f"Anthropic chat failed: {type(exc).__name__} status={status}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        if getattr(response, "stop_reason", None) == "refusal":
            raise LLMUnavailable("Anthropic model refused the request")
        texts, tool_calls, raw_blocks = [], [], []
        for block in response.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "tool_use":
                tool_calls.append({"id": block.id, "function": {"name": block.name, "arguments": dict(block.input or {})}})
            raw_blocks.append(block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(block))
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cost = self.cost(prompt_tokens, output_tokens)
        record_model_usage(purpose=purpose, provider=self.provider, model=self.model, prompt_tokens=prompt_tokens,
                           output_tokens=output_tokens, latency_ms=round(latency_ms, 2), cost_usd=round(cost, 8))
        return normalised_response(
            content="".join(texts).strip(), tool_calls=tool_calls, provider=self.provider, model=self.model,
            prompt_tokens=prompt_tokens, output_tokens=output_tokens, latency_ms=latency_ms, cost_usd=cost,
            extra_message={"provider_content": raw_blocks},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.embedder is None:
            raise LLMUnavailable("No local embedding model configured")
        return self.embedder.embed(texts)

    def health(self) -> dict:
        embedding = self.embedder.health() if self.embedder else {"available": False}
        return {
            "available": True,
            "chat_model_loaded": True,  # hosted model; reachability is checked per call
            "embedding_model_loaded": bool(embedding.get("embedding_model_loaded")),
            "embedding_runtime_available": bool(embedding.get("available")),
            "models": [self.model, *([self.embedding_model] if self.embedding_model else [])],
        }
