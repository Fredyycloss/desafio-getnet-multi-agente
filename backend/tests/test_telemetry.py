"""Prometheus /metrics and OpenTelemetry spans whose trace id is the API trace_id."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_endpoint_exposes_pipeline_metrics_without_identifiers(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "m.sqlite3"))
    from app.main import app
    with TestClient(app) as c:
        c.post("/api/chat", json={"message": "A Get Lite tem aluguel mensal?", "user_id": "cliente1988"})
        c.post("/api/chat", json={"message": "Quero falar com um atendente.", "user_id": "cliente1988"})
        text = c.get("/metrics").text
    for name in ("getnet_http_request_seconds_bucket", "getnet_stage_seconds_bucket", "getnet_chat_turns_total",
                 "getnet_critic_reviews_total", "getnet_handoffs_total", "getnet_human_queue_size", "getnet_corpus_info"):
        assert name in text, name
    assert "cliente1988" not in text and "Get Lite tem aluguel" not in text


def test_otel_trace_id_is_the_request_trace_id(monkeypatch, tmp_path):

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app import telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider(id_generator=telemetry.RequestIdGenerator())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.sqlite3"))
    from app.main import app
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"message": "A Get Lite tem aluguel mensal?", "user_id": "u"}, headers={"X-Request-ID": trace_id})
    assert r.json()["trace_id"] == trace_id
    spans = [s for s in exporter.get_finished_spans() if format(s.context.trace_id, "032x") == trace_id]
    names = {s.name for s in spans}
    assert {"POST /api/chat", "context_intelligence", "knowledge_tool:search_getnet_knowledge", "critic_review"} <= names
    assert len(spans) >= 5 and len({s.context.trace_id for s in spans}) == 1

