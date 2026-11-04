"""Prometheus metrics (GET /metrics) and OpenTelemetry traces (V7-I, V6 block 10).

Traces: one span per HTTP request and one child span per pipeline stage (every agent, tool,
model call, Critic review and persistence step already runs inside ``observability.stage``).
The OpenTelemetry trace id IS the API trace_id returned in every response (X-Request-ID, a
32-hex id), so the id a customer or the benchmark sees opens the trace in Jaeger directly.
Export is enabled by OTEL_EXPORTER_OTLP_ENDPOINT (OTLP/HTTP, e.g. http://jaeger:4318); without it
the API uses the no-op tracer.

Metrics never carry message text, user ids or session ids as labels.
"""
from __future__ import annotations

import logging
import os
import random
import re
from contextvars import ContextVar

from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

logger = logging.getLogger(__name__)

_LAT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 45, 60, 90, 120)
HTTP_REQUESTS = Counter("getnet_http_requests_total", "HTTP requests", ["path", "status"])
HTTP_SECONDS = Histogram("getnet_http_request_seconds", "HTTP request latency", ["path"], buckets=_LAT_BUCKETS)
STAGE_SECONDS = Histogram("getnet_stage_seconds", "Pipeline stage latency (agents, tools, model calls)",
                          ["stage", "component", "status"], buckets=_LAT_BUCKETS)
LLM_CALLS = Counter("getnet_llm_calls_total", "Model calls", ["purpose", "provider"])
LLM_TOKENS = Counter("getnet_llm_tokens_total", "Model tokens", ["purpose", "provider", "kind"])
LLM_COST = Counter("getnet_llm_cost_usd_total", "Model cost in USD", ["provider"])
LLM_ERRORS = Counter("getnet_llm_provider_errors_total", "Failed or timed-out model calls", ["stage", "status"])
CHAT_TURNS = Counter("getnet_chat_turns_total", "Chat turns", ["orchestration_mode", "intent"])
DEGRADED = Counter("getnet_degraded_total", "Degraded answers", ["reason"])
CRITIC = Counter("getnet_critic_reviews_total", "Critic verdicts", ["mode", "approved"])
HANDOFFS = Counter("getnet_handoffs_total", "Human hand-offs created", ["severity"])
CORPUS = Gauge("getnet_corpus_info", "Knowledge corpus version in use", ["version"])
QUEUE_SIZE = Gauge("getnet_human_queue_size", "Tickets waiting for an attendant")
QUEUE_OLDEST = Gauge("getnet_human_queue_oldest_seconds", "Age of the oldest ticket waiting for an attendant")

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_request_trace_id: ContextVar[str | None] = ContextVar("getnet_otel_trace_id", default=None)


def _label(value) -> str:
    return re.sub(r"[^a-zA-Z0-9_:.-]", "_", str(value or "none"))[:60]


# ------------------------------------------------------------------ tracing

from opentelemetry.sdk.trace.id_generator import RandomIdGenerator  # noqa: E402


class RequestIdGenerator(RandomIdGenerator):
    """Trace id = the request's 32-hex trace_id when there is one; random otherwise."""

    def is_trace_id_random(self) -> bool:
        return False  # derived from the request id (W3C random flag must not be claimed)

    def generate_trace_id(self) -> int:
        value = _request_trace_id.get()
        if value and _HEX32.match(value) and int(value, 16):
            return int(value, 16)
        return random.getrandbits(128) or 1


_tracer = trace.get_tracer("getnet-assist")


def setup_tracing() -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "getnet-assist-api")}),
                              id_generator=RequestIdGenerator())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    global _tracer
    _tracer = trace.get_tracer("getnet-assist")
    logger.info("otel_tracing_enabled endpoint=%s", endpoint)
    return True


def request_span(trace_id: str, name: str):
    """Root span of a request; its trace id is the request trace_id."""
    _request_trace_id.set(trace_id.lower())
    return _tracer.start_as_current_span(name, attributes={"getnet.trace_id": trace_id})


def stage_span(name: str, component: str):
    return _tracer.start_as_current_span(name, attributes={"getnet.component": component})


# ------------------------------------------------------------------ metric hooks

def observe_stage(name: str, component: str, status: str, seconds: float) -> None:
    base = name.split(":", 1)[0] if component == "model" else name
    STAGE_SECONDS.labels(_label(base), _label(component), status).observe(seconds)
    if component == "model" and status != "ok":
        LLM_ERRORS.labels(_label(base), status).inc()


def observe_model_call(fields: dict) -> None:
    purpose, provider = _label(fields.get("purpose")), _label(fields.get("provider"))
    LLM_CALLS.labels(purpose, provider).inc()
    for kind in ("prompt_tokens", "output_tokens"):
        if fields.get(kind):
            LLM_TOKENS.labels(purpose, provider, kind.split("_")[0]).inc(float(fields[kind]))
    if fields.get("cost_usd"):
        LLM_COST.labels(provider).inc(float(fields["cost_usd"]))


def observe_http(path: str, status: int, seconds: float) -> None:
    route = path if path in {"/api/chat", "/api/health", "/api/feedback", "/metrics"} else (
        "/api/operator/*" if path.startswith("/api/operator") else "/api/actions/*" if path.startswith("/api/actions")
        else "/api/sessions/*" if path.startswith("/api/sessions") else "/api/handoffs/*" if path.startswith("/api/handoffs") else "other")
    HTTP_REQUESTS.labels(route, str(status)).inc()
    HTTP_SECONDS.labels(route).observe(seconds)


def observe_turn(result: dict) -> None:
    CHAT_TURNS.labels(_label(result.get("orchestration_mode")), _label(result.get("intent"))).inc()
    if result.get("degraded"):
        DEGRADED.labels(_label(result.get("degraded_reason"))).inc()
    critic = result.get("critic") or {}
    if critic.get("mode"):
        CRITIC.labels(_label(critic.get("mode")), "true" if critic.get("approved") else "false").inc()
    if result.get("handoff_protocol") and result.get("handoff_status") == "queued":
        HANDOFFS.labels(_label(result.get("handoff_severity") or "normal")).inc()


def refresh_gauges(db, corpus_version: str | None) -> None:
    if corpus_version:
        CORPUS.clear()
        CORPUS.labels(_label(corpus_version)).set(1)
    try:
        with db.lock:
            row = db.conn.execute("SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM tickets WHERE status='queued'").fetchone()
        QUEUE_SIZE.set(row["n"] or 0)
        if row["oldest"]:
            from datetime import datetime, timezone
            oldest = datetime.fromisoformat(str(row["oldest"]).replace("Z", "+00:00"))
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            QUEUE_OLDEST.set(max(0.0, (datetime.now(timezone.utc) - oldest).total_seconds()))
        else:
            QUEUE_OLDEST.set(0)
    except Exception as exc:  # noqa: BLE001 - metrics never break the API
        logger.warning("queue_gauge_failed error=%s", type(exc).__name__)


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
