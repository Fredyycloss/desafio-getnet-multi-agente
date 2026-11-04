# Observability and replicas

## Start

```bash
# cloud mode + observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318 docker compose --profile observability up -d --build
# Jaeger http://localhost:16686 · Prometheus http://localhost:9090 (Alerts tab) · Grafana http://localhost:3000 (dashboard "Getnet Assist")
```

## Traces (OpenTelemetry → Jaeger)

- **Spans.** Each HTTP request is a root span. Every pipeline stage is a child span, one per stage the timeline already records:
  - Context Intelligence, RiskAssessment and PolicyGate;
  - each specialist, and each of its tools;
  - each model call (`anthropic_chat:<purpose>` / `ollama_chat:<purpose>`);
  - the Critic and persistence.
  Implementation: `backend/app/telemetry.py`, hooked into `observability.stage`.
- **Trace id.** The OpenTelemetry trace id **is** the API `trace_id`. It appears in the response, the `X-Request-ID` header, the logs, `/api/metrics` and the recorded cloud runs. Pasting it into Jaeger's search opens that exact turn.
- **Export.** OTLP/HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT`. Without it, the no-op tracer is used.
- **Test.** `backend/tests/test_telemetry.py` checks that the spans of one request share the response's `trace_id`.

## Metrics (GET /metrics, Prometheus format)

| Metric | Labels |
|---|---|
| `getnet_http_requests_total`, `getnet_http_request_seconds` | route, status |
| `getnet_stage_seconds` | stage (agent / tool / model call), component, status |
| `getnet_llm_calls_total`, `getnet_llm_tokens_total`, `getnet_llm_cost_usd_total` | purpose, provider, kind |
| `getnet_llm_provider_errors_total` | stage, status (error / timeout) |
| `getnet_chat_turns_total` | orchestration mode, intent |
| `getnet_degraded_total` | reason |
| `getnet_critic_reviews_total` | mode, approved |
| `getnet_handoffs_total` | severity |
| `getnet_human_queue_size`, `getnet_human_queue_oldest_seconds` | — |
| `getnet_corpus_info` | knowledge corpus version |

No label carries message text, user ids or session ids. The JSON summary at `/api/metrics` is kept for the UI and the benchmark.

## Dashboard and alerts

- **Dashboard.** [`observability/grafana/dashboards/getnet-assist.json`](../observability/grafana/dashboards/getnet-assist.json), provisioned automatically. Panels:
  - turns, p95, cost, tickets waiting;
  - latency p50/p95;
  - stage p95;
  - turns by orchestration mode;
  - degraded and Critic-rejection rates;
  - tokens by purpose;
  - provider errors and hand-offs.
- **Alerts.** [`observability/prometheus/alerts.yml`](../observability/prometheus/alerts.yml):

| Alert | Fires when |
|---|---|
| ChatLatencyP95High | p95 of `/api/chat` > 25 s for 10 min |
| DegradedAnswersHigh | > 10% of answers degraded in 30 min |
| CriticRejectionsHigh | > 20% of drafts rejected in 30 min |
| LLMProviderErrors | > 3 failed or timed-out model calls in 5 min |
| HumanQueueStalled | a hand-off waits > 15 min without an attendant |
| HumanQueueGrowing | > 10 tickets waiting for 15 min |
| ApiDown | a replica does not answer `/metrics` |

  Alertmanager routing (e-mail, chat) is a deployment choice and is not included.

- **Screenshots.** Jaeger and Grafana with a real cloud request: [`evidence/observability/`](evidence/observability/).

## Replicas

`API_PORTS=8000-8001 docker compose up -d --scale api=2` runs two API replicas.
- **Routing.** The web proxy (nginx, Docker DNS re-resolved every 10 s) spreads requests across them. Prometheus discovers each replica through DNS.
- **What makes the API stateless:**
  - every session, ticket, action, rate-limit counter, memory and feedback lives in the database, not in the process;
  - without `AUTH_SECRET`, demo mode stores one generated signing secret in the database, so a token from one replica is valid on the other;
  - background work (session summary) only writes to the database.
- **Single instance.** The Telegram worker is one long-polling service; Telegram allows one poller per bot.
- **Storage limit.** The replicas share the SQLite file on the `getnet_data` volume (WAL mode, same host). This is fine for a demonstration and a handful of replicas on one machine. It is **not** a multi-host setup.

**What changes in production (not implemented here):**
- **Postgres.** The data layer uses SQLite-specific SQL: `INSERT OR IGNORE`, `json_extract`, PRAGMAs. A Postgres backend with versioned migrations (e.g. Alembic) would replace `infra/database.py` and the modules that write their own tables (actions, HITL, memory, improvement, login limiter). It was planned in V7-I and is not delivered; see checklist item P3.
- Real identity instead of demo PINs.
- Alertmanager routes.
- TLS at the proxy.
- Rate limits at the edge.
- The Telegram worker under a single-instance lock.
