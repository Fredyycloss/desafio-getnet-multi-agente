"""Record and replay real model calls (VCR-style cassettes).

LLM_RECORD_DIR=<dir>   wraps the configured provider; every chat/embed call and its response
                       is appended to <dir>/cassette.jsonl. Requests carry prompts and synthetic
                       demo data only; credentials never reach this layer.
LLM_PROVIDER=replay    serves those responses back (LLM_REPLAY_DIR, default the latest folder in
                       docs/evidence/cloud_runs/). No key and no network: retrieval, tools, PolicyGate
                       and the deterministic Critic checks run for real; only the model text is replayed.

Matching, in order:
1. by request: when the API request carries the recorded X-Request-ID, the calls of that recorded
   request are served in their recorded order (matched by purpose). This is how a cassette
   replays a conversation even after prompts or tool lists changed in the code;
2. by key: a hash of the request with volatile parts masked (dates, times, UUIDs, protocols);
3. loosely: purpose + last user message.
A request that was never recorded raises LLMUnavailable("replay_miss"), and the pipeline takes its
normal degraded path. Replay never invents a model answer.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import re
import struct
import threading
import time
from pathlib import Path
from typing import Any

from .base import LLMProvider, LLMUnavailable, normalised_response

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[4]
CLOUD_RUNS = ROOT / "docs" / "evidence" / "cloud_runs"

_VOLATILE = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"), "<DATE>"),
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "<DATE>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<UUID>"),
    (re.compile(r"\b[0-9a-f]{32}\b"), "<HEX>"),
    (re.compile(r"\bGET-\d{8}-[0-9A-F]{6}\b"), "<PROTOCOL>"),
    (re.compile(r"\b(?:bench|d\d+|s\d?)-[a-z0-9-]{6,}\b"), "<SESSION>"),
]


def mask(text: str) -> str:
    for pattern, repl in _VOLATILE:
        text = pattern.sub(repl, text)
    return text


def _canonical(obj: Any) -> str:
    return mask(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str))


def chat_key(messages: list[dict], tools: list[dict] | None, json_schema: dict | None, purpose: str) -> str:
    raw = _canonical({"m": [{"role": m.get("role"), "content": m.get("content"), "tool_calls": m.get("tool_calls")} for m in messages],
                      "t": [t.get("function", {}).get("name") for t in tools or []], "s": bool(json_schema), "p": purpose})
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def loose_key(messages: list[dict], purpose: str) -> str:
    """Second-chance match: purpose + the last user message only."""
    last = next((str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"), "")
    return hashlib.sha256(f"{purpose}|{mask(last)}".encode()).hexdigest()[:32]


def embed_key(texts: list[str]) -> str:
    return hashlib.sha256(_canonical(texts).encode()).hexdigest()[:32]


def _pack_vectors(vectors: list[list[float]]) -> str:
    flat = [x for v in vectors for x in v]
    return base64.b64encode(gzip.compress(struct.pack(f"<{len(flat)}e", *flat))).decode()


def _unpack_vectors(data: str, n: int) -> list[list[float]]:
    raw = gzip.decompress(base64.b64decode(data))
    flat = list(struct.unpack(f"<{len(raw) // 2}e", raw))
    dim = len(flat) // n if n else 0
    return [flat[i * dim:(i + 1) * dim] for i in range(n)]


class RecordingProvider(LLMProvider):
    """Transparent wrapper: same behaviour as the inner provider, plus a cassette entry per call."""

    def __init__(self, inner: LLMProvider, directory: str | Path):
        self.inner = inner
        self.path = Path(directory) / "cassette.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def __getattr__(self, name):  # provider, model, check_key, thinking, ...
        return getattr(self.inner, name)

    @property
    def provider(self):  # type: ignore[override]
        return self.inner.provider

    @property
    def model(self):  # type: ignore[override]
        return self.inner.model

    @property
    def embedding_model(self):  # type: ignore[override]
        return self.inner.embedding_model

    @property
    def default_budget_seconds(self):  # type: ignore[override]
        return self.inner.default_budget_seconds

    def _write(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None,
             temperature=0.0, max_tokens=None, purpose="chat") -> dict:
        result = self.inner.chat(messages, tools, json_mode=json_mode, json_schema=json_schema, think=think,
                                 temperature=temperature, max_tokens=max_tokens, purpose=purpose)
        from ...observability import current_timeline
        timeline = current_timeline()
        self._write({"kind": "chat", "trace_id": timeline.trace_id if timeline else None, "key": chat_key(messages, tools, json_schema, purpose), "loose": loose_key(messages, purpose),
                     "purpose": purpose, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "request": {"messages": messages, "tools": [t.get("function", {}).get("name") for t in tools or []],
                                 "json_schema": bool(json_schema), "max_tokens": max_tokens},
                     "response": {k: result.get(k) for k in ("content", "tool_calls", "usage", "provider", "model")}})
        return result

    def embed(self, texts):
        vectors = self.inner.embed(texts)
        self._write({"kind": "embed", "key": embed_key(texts), "n": len(texts), "model": self.inner.embedding_model,
                     "vectors_f16_gzip_b64": _pack_vectors(vectors)})
        return vectors

    def health(self) -> dict:
        return self.inner.health()

    def describe(self) -> dict:
        return {**self.inner.describe(), "recording": True}


def _superseded(run: Path) -> bool:
    try:
        return bool(json.loads((run / "manifest.json").read_text(encoding="utf-8")).get("superseded_by"))
    except (OSError, ValueError):
        return False


def latest_cloud_run() -> Path | None:
    """Most recent recorded run (by folder name), skipping runs marked superseded_by in manifest.json."""
    runs = sorted(p for p in CLOUD_RUNS.glob("*") if p.is_dir() and any(p.glob("cassette.jsonl*")) and not _superseded(p))
    return runs[-1] if runs else None


class ReplayProvider(LLMProvider):
    provider = "replay"
    default_budget_seconds = 60.0

    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else latest_cloud_run()
        if self.directory is None:
            raise LLMUnavailable("no recorded cloud run found for replay")
        self.chats: dict[str, list[dict]] = {}
        self.loose: dict[str, list[dict]] = {}
        self.embeds: dict[str, dict] = {}
        self.by_trace: dict[str, list[dict]] = {}
        self._cursor: dict[str, int] = {}
        ordered: list[dict] = []
        self.misses: list[dict] = []
        models = set()
        for path in sorted(self.directory.glob("cassette.jsonl*")):
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry["kind"] == "chat":
                        ordered.append(entry)
                        if entry.get("trace_id"):
                            self.by_trace.setdefault(entry["trace_id"], []).append(entry)
                        self.chats.setdefault(entry["key"], []).append(entry)
                        self.loose.setdefault(entry["loose"], []).append(entry)
                        models.add(entry["response"].get("model") or "")
                    elif entry["kind"] == "embed":
                        self.embeds[entry["key"]] = entry
                        self.embedding_model = entry.get("model") or self.embedding_model
        if not self.by_trace:
            self._align_with_turns(ordered)
        self.model = "replay:" + ",".join(sorted(m for m in models if m))
        logger.info("replay_loaded dir=%s chats=%d embeds=%d", self.directory, sum(map(len, self.chats.values())), len(self.embeds))

    def _align_with_turns(self, ordered: list[dict]) -> None:
        """Recordings without trace_id per entry: the benchmark sends one request at a time, so the
        cassette is in request order and turns.jsonl lists each request's model calls (purposes)."""
        turns_path = self.directory / "turns.jsonl"
        if not turns_path.exists():
            return
        pos = 0
        for line in turns_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            turn = json.loads(line)
            purposes = [c.get("purpose") for c in ((turn.get("response") or {}).get("model_usage") or {}).get("calls", [])]
            if not purposes:
                continue
            # Calls of other requests may sit in between (warm-up, operator summaries): find this request's run.
            for start in range(pos, len(ordered) - len(purposes) + 1):
                if [e["purpose"] for e in ordered[start:start + len(purposes)]] == purposes:
                    self.by_trace[turn["trace_id"]] = ordered[start:start + len(purposes)]
                    pos = start + len(purposes)
                    break

    def _from_trace(self, purpose: str) -> dict | None:
        from ...observability import current_timeline
        timeline = current_timeline()
        entries = self.by_trace.get(timeline.trace_id) if timeline else None
        if not entries:
            return None
        cursor = self._cursor.get("trace:" + timeline.trace_id, 0)
        for i in range(cursor, len(entries)):
            if entries[i]["purpose"] == purpose:
                self._cursor["trace:" + timeline.trace_id] = i + 1
                return entries[i]
        return None

    def _next(self, bucket: str, entries: list[dict]) -> dict:
        i = self._cursor.get(bucket, 0)
        self._cursor[bucket] = i + 1
        return entries[min(i, len(entries) - 1)]

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None,
             temperature=0.0, max_tokens=None, purpose="chat") -> dict:
        key = chat_key(messages, tools, json_schema, purpose)
        traced = self._from_trace(purpose)
        if traced is not None:
            recorded, match = traced["response"], "request"
        else:
            entries, match = self.chats.get(key), "exact"
            if not entries:
                entries, match = self.loose.get(loose_key(messages, purpose)), "loose"
            if not entries:
                self.misses.append({"purpose": purpose, "key": key})
                logger.warning("replay_miss purpose=%s key=%s", purpose, key)
                raise LLMUnavailable("replay_miss")
            recorded = self._next(f"{match}:{key}", entries)["response"]
        usage = recorded.get("usage") or {}
        response = normalised_response(content=recorded.get("content") or "", tool_calls=recorded.get("tool_calls") or [],
                                       provider=self.provider, model=f"replay:{recorded.get('model')}",
                                       prompt_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("output_tokens"),
                                       latency_ms=0.0, cost_usd=0.0)
        response["replay_match"] = match
        from ...observability import record_model_usage
        record_model_usage(purpose=purpose, provider=self.provider, model=response["model"],
                           prompt_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("output_tokens"))
        return response

    def embed(self, texts):
        entry = self.embeds.get(embed_key(texts))
        if entry is None:
            raise LLMUnavailable("replay_miss_embedding")
        return _unpack_vectors(entry["vectors_f16_gzip_b64"], entry["n"])

    def health(self) -> dict:
        return {"available": True, "chat_model_loaded": True, "embedding_model_loaded": bool(self.embeds),
                "models": [self.model], "replay_dir": str(self.directory.relative_to(ROOT)) if self.directory.is_relative_to(ROOT) else str(self.directory)}

    def describe(self) -> dict:
        return {**super().describe(), "replay_dir": self.health()["replay_dir"]}
