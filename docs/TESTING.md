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
| `test_critic_agent.py`, `test_grounding.py` | Critic approves grounded answers and rejects invented values, missing citations and secret requests |
| `test_context_intelligence.py`, `test_risk_assessment_context.py`, `test_clarification.py`, `test_human_request_guardrail.py` | schema validation, deterministic hazards, menus, human priority |
| `test_real_database_tools.py`, `test_real_knowledge_retrieval.py`, `test_web_research_tools.py`, `test_api_integration.py`, `test_security_and_memory.py` | real tools, retrieval, API wiring, memory, redaction, audit |

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
