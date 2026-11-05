# Testing

## Backend: no key, no internet, no model

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
PYTHONPATH=. OLLAMA_ENABLED=false python -m pytest -q
```

The same suite also runs in Docker with `docker compose --profile test run --build --rm tests`.

**Test doubles.** Model calls are replaced at the transport boundary by scripted fakes (`chat(...)` returning fixed JSON or tool calls). Everything else is real:
- Supervisor, specialists and PolicyGate;
- Critic and grounding;
- SQLite tools;
- BM25 retrieval over the committed corpus;
- FastAPI routes and authentication.

Web providers are stubbed at HTTP level. The Anthropic adapter is tested with a fake SDK client, with no key and no network.

| File | Focus |
|---|---|
| `test_agents_and_orchestration.py` | fast path vs planning loop, real specialists as tools, Critic rejection → re-plan → handoff, budget exhaustion → labelled fallback, Payments vs Support |
| `test_policy_and_datasets.py` | PolicyGate order, D3/D4 flows, decline error → Payments, zero safety false negatives, dataset disjointness and the n-gram leak check |
| `test_auth_and_isolation.py` | demo login/token, 401/403/404 boundaries, A × B isolation, prompt injection in the message and in a RAG document |
| `test_llm_providers.py`, `test_llm_ollama_adapter.py` | provider contracts, selection, budget, key never leaked, no direct provider imports in agents |
| `test_cloud_key_failures.py` | real Anthropic SDK over a simulated HTTP transport: 401/403/no credit → health message, `degraded_reason`, optional offline fallback in the trace; the key never shows |
| `test_intent_classifier.py` | hybrid Context Intelligence: kNN decides clear turns without the LLM; mandatory triggers call it; intent examples share no phrase with datasets or benchmark; `llm_knn_route` re-routes only safe untriggered turns and keeps multi-agent plans |
| `test_set_api_key_script.py` | `scripts/set-api-key.sh` in temporary directories only: creates `.env` from the example, replaces only the key line, rejects invalid prefixes, never prints the key |
| `test_critic_agent.py`, `test_grounding.py` | Critic approves grounded answers and rejects invented values, missing citations and secret requests |
| `test_context_intelligence.py`, `test_risk_assessment_context.py`, `test_clarification.py`, `test_human_request_guardrail.py` | schema validation, deterministic hazards, menus, human priority |
| `test_real_database_tools.py`, `test_real_knowledge_retrieval.py`, `test_web_research_tools.py`, `test_api_integration.py`, `test_security_and_memory.py` | real tools, retrieval, API wiring, memory, redaction, audit |
| `test_hitl_api.py`, `test_hitl_telegram.py` | operator console (claim, reply, resolve, return to AI), live resumption, Telegram worker over a simulated Bot API, unauthorized operator, Telegram outage → console keeps working |
| `test_knowledge_crawler.py`, `test_knowledge_snapshot.py`, `test_knowledge_tools.py` | crawler discovery and extraction, snapshot loading offline, Knowledge Agent tool selection |
| `test_critic_challenge.py` | challenge mode corrupts the first draft; the Critic catches it and the re-plan fixes it |
| `test_replay_cassette.py` | the committed cloud recording replayed without a key: same outcome per turn, misses reported |
| `test_login_security.py` | account lockout, per-IP ceiling, chat rate limit, non-demo mode (scrypt credentials, required `AUTH_SECRET`) |
| `test_write_actions.py` | write tools only propose; confirmation, expiry, idempotency, audit |
| `test_anonymous_and_topics.py` | literal payload without a token; customer tools answer `login_required`; home suggestions route by topic |
| `test_ablation.py` | each `ABLATION` value switches off exactly one stage |
| `test_session_memory.py` | summary and facts after a long session, redaction, isolation; the memory note survives the history window and reaches the answer writer; `recall_conversation` answers from it |
| `test_excerpt.py` | evidence excerpts focus on the part of a chunk the question (Knowledge) or the answer (Critic) talks about |
| `test_improvement_loop.py` | feedback, validated answers invalidated by corpus version, knowledge-gap promotion only by an operator, overlap with evaluation sets refused |
| `test_telemetry.py` | OpenTelemetry spans share the response `trace_id`; Prometheus metrics carry no user data |
| `test_injection_defense.py` | per-agent tool allowlist, schema-checked arguments, output filter for other customers' identifiers, delimited retrieved content |

**Count:** 367 tests pass on 05/11/2026 (`pytest -q`). The replay test also runs as its own CI step.

## Browser: Playwright

```bash
cd frontend && npm ci && npx playwright install chromium
E2E_PYTHON=../backend/.venv/bin/python npm run test:e2e
```

`frontend/e2e/support-flow.spec.ts` starts the real API on port 8100 with `LLM_PROVIDER=fixture` (a scripted, deterministic provider) and the Vite dev server on port 5180. It then drives Chromium through:

1. demo login;
2. a product question with sources;
3. an ambiguous message → menu;
4. numeric selection → intake question;
5. "Falar com atendente" → protocol;
6. protocol status.

## Live model

These need a running stack and a real model; see [EVALUATION.md](EVALUATION.md):
- `scripts/benchmark_latency.py`;
- `python -m app.evaluation.run_context_eval --split dev|heldout`.

## CI

`.github/workflows/build.yml` runs:
- backend compile, tests and the offline evaluation;
- frontend `npm ci` and build;
- the Playwright flow;
- a Docker Compose build and smoke test (health, web, `/api/agents`), ending with `docker compose down`, never `-v`.

The cloud model and Qwen are not used in CI.
