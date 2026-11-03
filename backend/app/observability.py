"""PII-safe per-request timing collection for the support pipeline.

Only component names, status and elapsed time are collected.  User messages,
identifiers and model prompts are intentionally excluded from this timeline.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TraceTimeline:
    trace_id: str
    events: list[dict] = field(default_factory=list)
    model_calls: list[dict] = field(default_factory=list)
    # Monotonic deadline for all model calls of this request (None = unbounded).
    llm_deadline: float | None = None

    def snapshot(self) -> list[dict]:
        return [dict(event) for event in self.events]

    def model_usage(self) -> dict:
        """Per-request LLM cost summary: number of calls and token counts."""
        prompt = sum(int(c.get("prompt_tokens") or 0) for c in self.model_calls)
        output = sum(int(c.get("output_tokens") or 0) for c in self.model_calls)
        cost = sum(float(c.get("cost_usd") or 0) for c in self.model_calls)
        return {
            "llm_calls": len(self.model_calls),
            "prompt_tokens": prompt,
            "output_tokens": output,
            "cost_usd": round(cost, 8),
            "calls": [dict(call) for call in self.model_calls],
        }


_timeline: ContextVar[TraceTimeline | None] = ContextVar("getnet_trace_timeline", default=None)


def current_timeline() -> TraceTimeline | None:
    return _timeline.get()


_default_budget_seconds = 90.0


def set_default_llm_budget(seconds: float) -> None:
    """Provider profile default (cloud 30 s, local 150 s); REQUEST_LLM_BUDGET_SECONDS overrides it."""
    global _default_budget_seconds
    _default_budget_seconds = float(seconds)


def _llm_budget_seconds() -> float | None:
    raw = os.getenv("REQUEST_LLM_BUDGET_SECONDS", "").strip()
    try:
        budget = float(raw) if raw else _default_budget_seconds
    except ValueError:
        budget = _default_budget_seconds
    return budget if budget > 0 else None


def llm_budget_seconds() -> float | None:
    return _llm_budget_seconds()


def start_timeline(trace_id: str) -> Token:
    """Start a request-local timeline and return its ContextVar token."""
    budget = _llm_budget_seconds()
    deadline = time.monotonic() + budget if budget is not None else None
    return _timeline.set(TraceTimeline(trace_id=trace_id, llm_deadline=deadline))


def llm_time_remaining() -> float | None:
    """Seconds left in this request's LLM budget, or None when unbounded/untraced."""
    timeline = current_timeline()
    if timeline is None or timeline.llm_deadline is None:
        return None
    return timeline.llm_deadline - time.monotonic()


def finish_timeline(token: Token) -> list[dict]:
    timeline = _timeline.get()
    events = timeline.snapshot() if timeline else []
    _timeline.reset(token)
    return events


def record_model_usage(**fields) -> None:
    """Attach token/duration counters reported by the model runtime (no content)."""
    timeline = current_timeline()
    if timeline is None:
        return
    timeline.model_calls.append(fields)
    logger.info(
        "model_usage trace_id=%s purpose=%s provider=%s model=%s prompt_tokens=%s output_tokens=%s latency_ms=%s cost_usd=%s load_ms=%s prompt_ms=%s generation_ms=%s",
        timeline.trace_id, fields.get("purpose"), fields.get("provider"), fields.get("model"), fields.get("prompt_tokens"),
        fields.get("output_tokens"), fields.get("latency_ms"), fields.get("cost_usd"), fields.get("load_ms"),
        fields.get("prompt_ms"), fields.get("generation_ms"),
    )


def _status_for_exception(exc: BaseException) -> str:
    description = f"{type(exc).__name__} {exc}".casefold()
    return "timeout" if "timeout" in description else "error"


@contextmanager
def stage(name: str, component: str):
    """Record duration and outcome for one pipeline stage when tracing is active."""
    timeline = current_timeline()
    started = time.perf_counter()
    status = "ok"
    try:
        yield
    except BaseException as exc:
        status = _status_for_exception(exc)
        raise
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if timeline is not None:
            event = {
                "stage": name,
                "component": component,
                "status": status,
                "duration_ms": duration_ms,
            }
            timeline.events.append(event)
            logger.info(
                "pipeline_stage trace_id=%s stage=%s component=%s status=%s duration_ms=%.2f",
                timeline.trace_id,
                name,
                component,
                status,
                duration_ms,
            )
