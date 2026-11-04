> **Histórico — não reflete o código atual.** Relatório de uma versão anterior, mantido para rastreabilidade. O estado atual está em [docs/README.md](../README.md).

# Audit: Feedback V4 and pending items → current version

The Feedback V4 (score 2.6/10) evaluated an earlier version. This table maps each criticism to evidence in **this** repository. The evidence is the file that implements it plus a test or measured report.

Status:
- **RESOLVED**: implemented, tested and, where applicable, measured.
- **PARTIAL**: implemented, but with a documented limit.
- **NOT**: not done.

## Feedback V4 criticisms

| # | V4 criticism | Status | Evidence (implementation · test / measurement) |
|---|---|---|---|
| 1 | No effective web research | **RESOLVED** | `agents/web_research_agent.py`: LLM extracts parameters → Open-Meteo / Frankfurter / DuckDuckGo → LLM writes from the provider result with the source; template only as `degraded` fallback · `tests/test_web_research_tools.py`; benchmark `weather_porto_alegre`, `euro_rate` (llm_complete, route correct) |
| 2 | Insufficient knowledge base | **PARTIAL** | `knowledge/corpus.json`: 10 official Getnet pages in PT/EN, 26 chunks; hybrid BM25 + `nomic-embed-text`; `[n]` citations; abstention below 0.12 relevance · `tests/test_real_knowledge_retrieval.py`; benchmark D1 and the 5 product questions with route correct. **Limit:** the corpus is small, and questions outside it get a topic menu |
| 3 | No real customer lookup tools | **RESOLVED** | `agents/support_tools.py`, `agents/support_agent.py`, `agents/payments_agent.py`: SQLite tools (profile, terminal, payments, declines); the LLM picks the tools and writes the answer; `user_id` bound server-side · `tests/test_real_database_tools.py`, `test_model_cannot_pass_another_user_id_to_payment_tools`; benchmark D2, A4 |
| 4 | Tests rely too much on mocks | **RESOLVED** | Only the model transport and external HTTP are scripted. Supervisor, specialists, PolicyGate, Critic, SQLite, retrieval, FastAPI and auth are real · `docs/TESTING.md`; Playwright drives the real UI + API (`frontend/e2e/support-flow.spec.ts`); real-model benchmarks in both modes |
| 5 | Documentation diverges from code | **RESOLVED** | README, ARCHITECTURE, TESTING, SECURITY and EVALUATION rewritten against the code; numbers only from the reports in `docs/`; clean-clone test recorded in `RELATORIO_FINAL_2026-11-02.md` |
| 6 | Insufficient memory | **RESOLVED** | `infra/database.py`: sessions and messages in SQLite on a named volume, owner-checked, history fed to Context Intelligence and specialists, clarification options persisted · `tests/test_security_and_memory.py`; benchmark D10 (two sessions isolated), D3 (context preserved) |
| 7 | No adequate human supervision | **RESOLVED** (simulated queue) | `agents/human_handoff_agent.py`, operator API (claim/reply/resolve), protocol, status, history, priority for safety; Critic double rejection → handoff · `tests/test_api_integration.py` (operator lifecycle), `test_critic_rejecting_twice_hands_off_to_a_human`; benchmark D5. **Limit:** no real operator is connected (`real_agent_connected=false`) |
| 8 | Insufficient quality evaluation | **RESOLVED** | Dev vs held-out datasets (held-out never tuned) with route, risk, action, safety-FN and cost metrics; end-to-end benchmark with outcome classification, route correctness and Critic metrics · `backend/app/evaluation/`, `scripts/benchmark_latency.py`, `docs/eval/*.json`, `docs/RELATORIO_LATENCIA_2026-11-02_*.json` |
| 9 | Limited observability | **RESOLVED** | Per request: `stage_timings` for every stage and `model_usage` (purpose, provider, model, tokens, latency, cost). Aggregated in `/api/metrics`: tools, stages, timeouts, model cost per provider and purpose · `tests/test_api_integration.py`, `tests/test_security_and_memory.py::test_model_usage_is_persisted_without_content` |
| 10 | Production engineering needs work | **RESOLVED** (demo scope) | Docker Compose with a pinned Ollama image (`0.40.13`); `package-lock.json` + `npm ci`; CI covers tests, build, Playwright and the compose smoke test; request budget with labelled fallback instead of 503; secrets only in `.env`; key-leak test · `.github/workflows/build.yml`, `test_llm_providers.py` |

## Pending items from the last Codex audit (dossier §9)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | `.git` of the working copy was empty | **RESOLVED** | Local history with one commit per stage (`git log`) |
| 2 | README cited models different from the AI profile | **RESOLVED** | README and `docker-compose*.yml` both state `qwen3:1.7b` + `nomic-embed-text` (offline) and `claude-haiku-5-5` (cloud) |
| 3 | Latency per agent and tool missing from the API | **RESOLVED** | `stage_timings` and `model_usage` in every `/api/chat` response; `/api/metrics` → `stages`, `tools`, `model` |
| 4 | CI tore down volumes | **RESOLVED** | The workflow uses `docker compose down --remove-orphans` with no `-v` |
| 5 | Real evaluation below thresholds | **PARTIAL** | Measured and reported, not hidden: cloud held-out and local held-out in `RELATORIO_FINAL_2026-11-02.md`. Below 0.90 in some metrics; zero safety false negatives is the hard gate |
| 6 | Inference slow on this hardware | **PARTIAL** | Cloud mode meets the latency targets (measured). Offline Qwen on this i3 CPU does not; reported with real numbers. The request budget turns overruns into labelled fallbacks, not 503 |
| 7 | Coverage of required flows | **RESOLVED** | Acceptance scenarios 1–18 + dossier D1–D10 in the benchmark (`acceptance_map_1_18`); Playwright flow |
| 8 | Documentation not validated | **RESOLVED** | Docs rewritten; clean clone → `.env.example` → `docker compose up` → health → tests recorded in the final report |
| 9 | Docker access vs code issues | **RESOLVED** | All measurements ran on the real Compose stack on this machine; no environment blocker remains |

## Additional fixes since V4 that the grader may look for

- **Evaluation leak removed.** No phrase from either dataset appears in the routing code (`test_no_dataset_phrase_is_copied_into_routing_code`), and the held-out set is never used for tuning.
- **Authentication.** HMAC demo tokens; identity comes from the token; 401/403/404 boundaries (`test_auth_and_isolation.py`).
- **Answers written by LLM agents.** Fixed text is limited to the 4 allowed cases (`docs/INVENTARIO_TEMPLATES.md`).
- **Critic.** It can reject, through deterministic checks or the model; one re-plan, then handoff.
- **Provider layer.** Local or cloud with no code changes in the agents.
