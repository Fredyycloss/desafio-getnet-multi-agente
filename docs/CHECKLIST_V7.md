# Checklist V7 (supersedes CHECKLIST_V6)

Starting point: commit `ee74988` (published, CI green, feedback v2 = 7.3/10).

**Sources:**
- **V6**: `MISSAO_V6_COMPLETA` checklist and blocks;
- **V7**: `MISSAO_V7_RUMO_AO_10`;
- **FB2**: gaps and discounts in feedback v2;
- **SELF**: issues I raised myself (self-evaluation of `ee74988`, block reports, open defects).

**Block:** the V7 order number (1–13).

**Status:** ABERTO → RESOLVIDO / PARCIAL / NÃO, closed at the end with file, test and evidence.

## Knowledge and RAG (block 1)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| K1 | Corpus is 26 hand-written summaries of 10 pages; does not ingest `getnet.net/en` | V6, FB2, SELF | 1 | RESOLVIDO | `backend/app/knowledge/snapshots/2026-11-03/` (378 pages incl. getnet.net/en); `test_knowledge_snapshot.py` |
| K2 | Crawler never run; fixed 40-page limit | V6 | 1 | RESOLVIDO | `ingest_cli --max-pages` (default 2000), frontier exhausted at 378 pages; manifest `stopped_by` |
| K3 | Discovery via robots → sitemap → WP REST → links; JS pages; politeness; generic User-Agent | V6 1.1 | 1 | RESOLVIDO | `app/knowledge/crawler.py` (WP REST answers 404 on this site, documented); `test_knowledge_crawler.py` |
| K4 | Boilerplate removal, heading-based chunking, rich metadata, dedup | V6 1.2 | 1 | RESOLVIDO | `extract_page`, `remove_boilerplate`, `chunk_pages`; `test_knowledge_crawler.py` |
| K5 | Versioned snapshot + manifest; precomputed embeddings; offline boot; idempotent refresh command | V6 1.3 | 1 | RESOLVIDO | snapshot + `embeddings.json.gz` + manifest (timings); `load_documents()` offline; compose `knowledge-refresh` |
| K6 | Hand-written summaries removed or down-weighted (`curated_summary`), with justification | V6 1.3 | 1 | RESOLVIDO | `load_legacy_curated()` baseline only; README Knowledge section |
| K7 | Web search inside the Knowledge Agent (tools chosen by the LLM) | V6 1.4, SELF | 1 | RESOLVIDO | `agents/knowledge_tools.py`, `KnowledgeAgent.run`; `test_knowledge_tools.py` |
| K8 | DuckDuckGo scraping is fragile → stable sources (Wikipedia REST / DDG Instant Answer / optional key) | V6 1.4, SELF | 1 | RESOLVIDO | `agents/web_search_tool.py` (Brave key optional → Wikipedia REST → DDG Instant Answer); `test_web_research_tools.py` |
| K9 | FX without a tool call → degraded answer (regression) | SELF | 1 | PARCIAL | no-tool-call is a marked fallback (`test_no_tool_call_on_currency_question_is_a_marked_fallback...`); live rate measured in block 4 benchmark |
| K10 | Retrieval metric was recall@5 on 5 cases → ≥60 labelled questions; recall@1/3/5, MRR, abstention; old × new corpus; BM25 × dense × hybrid | V6 1.5, FB2 | 1 | RESOLVIDO | `run_retrieval_eval.py` + `retrieval_questions.json` (70); `docs/eval/RETRIEVAL_EVAL_2026-11-03.json` at d603949: hybrid R@5 0.78 vs legacy 0.40 |

## HITL (block 2)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| H1 | Simulated queue (`real_agent_connected=false`), no operator channel | FB2, V6 7, SELF | 2 | RESOLVIDO | `app/hitl/` (console + Telegram); `real_agent_connected` from channel heartbeat |
| H2 | Telegram channel: card with LLM summary, inline buttons, reply / `/r`, long-polling worker, authorized operators, audit | V7-A | 2 | RESOLVIDO | `app/hitl/telegram.py`, `telegram_worker.py`, compose `telegram-worker`; `test_hitl_telegram.py` (simulated Bot API) |
| H3 | Web operator console (queue, details, claim, reply, resolve) with individual login | V7-A, V6 7 | 2 | RESOLVIDO | `frontend/src/OperatorConsole.tsx` (`/operador`), `app/hitl/api.py`, `app/hitl/operators.py` (scrypt, roles) |
| H4 | Resumption: operator messages reach the customer live; customer talks to the human while `in_progress`; resolution summary in history; "return to AI with instruction" | V7-A, FB2 | 2 | RESOLVIDO | live polling `GET /api/sessions/{id}/messages?after_id`, ticket routing in `/api/chat`, resolution note, `return-to-ai` + `resume_if_pending`; `test_hitl_api.py` |
| H5 | `real_agent_connected` reflects reality | V7-A | 2 | RESOLVIDO | `HITLService.human_available()`; `test_full_cycle_operator_reply_live...` asserts true with console live |
| H6 | Tests: simulated Telegram transport, unauthorized operator, Telegram outage → console works; end-to-end resumption; Playwright customer + operator | V7-A | 2 | RESOLVIDO | `test_hitl_telegram.py` (8), `test_hitl_api.py` (4), `frontend/e2e/hitl-flow.spec.ts` (customer + operator) |
| H7 | Committed evidence: real transcript + Telegram screenshots + trace | V7-A | 2 | PARCIAL | console screenshots `docs/evidence/hitl/*.png`; Telegram transcript waits for the bot token |

## Answer quality and Critic (block 3)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| Q1 | No answer-quality measure (judge, groundedness, number check) | FB2, V7-B, V6 4 | 3 | RESOLVIDO | app/evaluation/answer_quality.py + run_answer_quality.py; cloud run docs/eval/ANSWER_QUALITY_cloud_run1_2026-11-03.json |
| Q2 | Quality set ≥60 with `must_include`/`must_not_include`/sources/values | V7-B | 3 | RESOLVIDO | answer_quality.jsonl: 63 items with must_include / must_not_include / sources |
| Q3 | Metrics: groundedness (judge + deterministic), number accuracy, coverage, correct citation, language, abstention, usefulness 1–5 | V7-B | 3 | RESOLVIDO | coverage, forbidden absent, numbers supported, citation correct, abstention, judge correct/grounded |
| Q4 | LLM-as-judge with a versioned rubric, documented judge model, temperature 0, cost | V7-B | 3 | RESOLVIDO | docs/evaluation/JUDGE_RUBRIC.md; judge claude-sonnet-5-5, temperature 0, cost recorded |
| Q5 | Human labels: ~80 answers (incl. injected bad ones) + labelling tool; Critic/judge P/R/F1, kappa; calibrate on half, report on the other half | V7-B | 3 | PARCIAL | label_cli + 83 labelling items + calibrate_critic.py ready; human labels await the author (asked in the final report) |
| Q6 | Critic approved 100% / calibration 21%→0% between runs: explain and measure | FB2, SELF, V6 4 | 3 | PARCIAL | Strict vs material explained (docs/RELATORIO_QUALIDADE_2026-11-04.md); Critic now decides by per-issue severity (eac1d96); human-label calibration pending Q5 |
| Q7 | `heldout_v1` (seen) + `heldout_v2` ≥100 new cases with recorded origin; 3 runs per mode, mean ± sd | V6 4, SELF | 3 | RESOLVIDO | heldout_v2 109 cases; 3 runs per mode: cloud route 0.932±0.008, FN 0; offline route 0.184±0.033, FN 0 |
| Q8 | `RELATORIO_QUALIDADE_<data>.md` | V7-B | 3 | RESOLVIDO | docs/RELATORIO_QUALIDADE_2026-11-04.md |

## Orchestration (block 4)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| O1 | Fast path dominant (16/17); multi-specialist in 1 case | FB2, SELF | 4 | RESOLVIDO | Cloud run 04/11: 22 fast path / 18 planning in the orchestration set; 18/20 multi-intent planned (docs/RELATORIO_LATENCIA_2026-11-04_cloud-v7.json) |
| O2 | Multi-intent scenarios: Supervisor plans with ≥2 specialists; trace plan → observation → decision | V6 5, V7-C | 4 | RESOLVIDO | 20/20 multi-intent cases called every expected specialist; trace shows plan → tool:* → decision (`turns.jsonl`) |
| O3 | Benchmark ≥60 requests per mode (≥20 multi-intent, ≥10 needing a re-plan) + 10 challenge + 18 acceptance, **no NOT_RUN** | V7-C, FB2 | 4 | PARCIAL | Cloud: 91 requests (34 latency, 17 functional, 40 orchestration); acceptance 1–18 all PASS, no NOT_RUN. Offline run of the same set: block 3 part 2 / 12 |
| O4 | Critic with real traffic + `CRITIC_CHALLENGE_MODE` (off in production): rejection, re-plan, success after re-plan, handoff | V7-C | 4 | RESOLVIDO | Challenge 10/10 caught, 10/10 fixed by re-plan, 0 leaked; natural set 1 rejection fixed; first run exposed Critic defects fixed in eac1d96 (before/after in docs/EVIDENCE.md) |
| O5 | Supervisor of ~800 lines → modules (fast path, planner, replanner, composer) without behaviour change | V6 5, SELF | 4 | RESOLVIDO | `agents/supervisor/` (constants, fast_path, planner, replanner, composer, menus); 292 tests unchanged after the split (adf07e6) |

## Evidence without execution (block 5)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| E1 | Cloud mode not reproduced by the evaluator (no PyPI, executes nothing) | FB2 | 5 | RESOLVIDO | Committed recordings + replay + screenshots: cloud mode checkable without executing (docs/EVIDENCE.md) |
| E2 | Real cloud recordings (JSONL with full traces) in `docs/evidence/cloud_runs/` | V7-D | 5 | RESOLVIDO | `docs/evidence/cloud_runs/2026-11-04/` (92 turns, 418 model calls, US$ 0.0987) + pre-fix run |
| E3 | `replay` provider (cassette) + replay test in CI without a key | V7-D | 5 | RESOLVIDO | `LLM_PROVIDER=replay`; CI step; 53/53 reproducible turns same outcome, 0 misses |
| E4 | Evidence page in the README with direct links | V7-D | 5 | RESOLVIDO | `docs/EVIDENCE.md`, linked from README "For the evaluator" |
| E5 | UI screenshot gallery generated by Playwright | V7-D | 5 | RESOLVIDO | `docs/evidence/ui/` (8 screenshots over the replayed cloud run) |

## Secrets and identity (block 6)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| S1 | API key sent in plain text by message → policy: never distribute a key; evaluator uses their own key or replay/offline; old key revoked (user confirms) | FB2, V7-E | 6 | RESOLVIDO | Policy in README + docs/SECURITY.md; the author confirmed on 04/11/2026 that the emailed key was revoked |
| S2 | Secret scanning in CI (pinned gitleaks) + documented pre-commit hook | V7-E | 6 | RESOLVIDO | CI job gitleaks v8.21.2 (pinned image, redacted) + `.pre-commit-config.yaml`; local scan: no leaks |
| S3 | Shared operator key → individual operators (hashed password, roles, expiry, per-operator audit) | FB2, V7-E | 6 | RESOLVIDO | Block 2: scrypt accounts, roles, expiring tokens, per-operator audit; shared key bootstrap-only (off by default) |
| S4 | Rate limiting + lockout on customer and operator login; basic rate limit on `/api/chat` | V7-E, V6 8, SELF | 6 | RESOLVIDO | `app/login_limiter.py` (DB-backed): account lockout, per-address ceiling, per-customer chat limit; tests/test_login_security.py |
| S5 | Public PINs → explicit `DEMO_MODE`; outside demo, configured secret required and no user listing | V7-E, SELF | 6 | RESOLVIDO | `DEMO_MODE=false`: no user list, scrypt customer credentials, AUTH_SECRET required; UI asks for the id |
| S6 | Per-process `AUTH_SECRET` → required outside demo | V6 8, SELF | 12 | RESOLVIDO | Block 6: DEMO_MODE=false refuses to start without AUTH_SECRET; demo: DB-shared secret + /api/health warning |
| S7 | Injection beyond the prompt: tool allowlist per agent, schema-checked args, output filter for other customers' identifiers, delimited retrieved content; new tests (including injection inside a site page) | V6 8, SELF | 12 | RESOLVIDO | Schema-checked args, per-agent allowlist, output filter, <untrusted_data>; tests/test_injection_defense.py (5) |
| S8 | `SECURITY.md`: threats × controls × tests | V6 8 | 12 | RESOLVIDO | docs/SECURITY.md 'Threats × controls × tests' |

## Write tools (block 7)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| T1 | Read-only tools → ≥3 write actions with confirmation, idempotency and audit | FB2, V7-F | 7 | RESOLVIDO | 4 actions: technical visit, supply request, transaction dispute, terminal block (docs/WRITE_ACTIONS.md) |
| T2 | Session-bound expiring confirmation token; the LLM never executes without it; sensitive action needs reinforced confirmation | V7-F | 7 | RESOLVIDO | Pending action bound to customer + conversation, expiry, one-time token (not stored in history); block needs typed phrase; only propose_* tools |
| T3 | Tests: no confirmation → no action; another session's confirmation rejected; idempotency; audit; Critic checks the described effect | V7-F | 7 | RESOLVIDO | tests/test_write_actions.py (7): no confirmation, other session/customer/bad token, idempotency, cancel/expiry, ownership, typed phrase; Critic grounding over the record |
| T4 | Few synthetic data → more customers, terminals, sales and declines (existing ones kept) | V6, SELF | 7 | RESOLVIDO | TX-DEMO-1005, TX-DEMO-2002, TX-DEMO-3001 added; 'yesterday' totals of existing scenarios unchanged |

## Business and contract (block 8)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| B1 | Home-screen suggestions fall into the menu; a clear Payment Link question asks for clarification | V6 2, SELF | 8 | RESOLVIDO | Cloud: 12/12 suggestion requests answered with no menu (docs/RELATORIO_LATENCIA_2026-11-04_cloud-v7-block8.json); offline in block 12 run |
| B2 | `selected_topic` on suggestions; typed suggestions answered by real understanding (pt/en, both modes); Playwright clicks all 4 | V6 2 | 8 | PARCIAL | selected_topic implemented + tests (scripted unsure model still dispatches); Playwright clicks all 4 (e2e/home-suggestions.spec.ts); cloud typed pt/en + clicked 12/12; offline measurement pending (block 12 benchmark) |
| B3 | Literal challenge payload returns 401 → anonymous session; customer data requires login | V6 3, SELF | 8 | RESOLVIDO | No token = anonymous session; customer tools answer login_required; cloud B3 check 21/21 PASS (docs/RELATORIO_LATENCIA_2026-11-04_cloud-v7-block8.json); tests/test_anonymous_and_topics.py; README shows the literal curl first |
| B4 | Acceptance scenarios marked `NOT_RUN` in the report | FB2 | 4/8 | RESOLVIDO | Cloud run 2026-11-04: acceptance map 1–18 with no NOT_RUN |

## Engineering judgment (block 9)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| J1 | Heavy chain without a measure that justifies it → ablation (full, no Critic, no CI, no PolicyGate (safety set only), fast path only, planning only) | FB2, V7-G | 9 | RESOLVIDO | docs/eval/ABLATION_2026-11-04.json (commit 861ada7, 1 run per config): no PolicyGate → 19/19 dangerous missed; no CI → 4 missed, +50% cost; no Critic → numbers supported 56/58 → 52/58 |
| J2 | Simplify what does not pay for itself; `docs/ABLACAO_<data>.md` | V7-G | 9 | RESOLVIDO | docs/ABLACAO_2026-11-04.md: every stage pays for itself on safety, grounding or cost; nothing removed (the measurement shows no gain from removal); planning-mode citation loss recorded as a finding |
| J3 | Extensive deterministic policy (risk regex, menus) → justify with numbers (cases decided by each rule) | V6, SELF | 9 | PARCIAL | RiskAssessment alone on heldout_v2: 15/19 dangerous flagged, 3/90 false alarms; its 4 misses are the ones CI covers (docs/ABLACAO_2026-11-04.md). Menus not attributed per rule |

## Memory and continuous improvement (block 10)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| M1 | No long-conversation summary → incremental summary + structured session memory; 30-turn test; tokens saved | FB2, V7-H, SELF | 10 | PARCIAL | app/memory.py + recall_conversation tool; 30-turn test; measured on/off (docs/eval/MEMORY_EVAL_2026-11-04.json, 1caa3cd): early-fact recall 2/4 on vs 0/4 off; no token saving at 16 turns; 2 misses open |
| M2 | Improvement loop: refresh, 👍/👎 feedback, validated answers (invalidated by corpus version), knowledge-gap queue promoted only by an operator | V6 6, SELF | 10 | RESOLVIDO | app/improvement.py: feedback, validated answers by corpus version, gap queue promoted only by a supervisor; tests/test_improvement_loop.py |

## Observability and production (block 11)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| P1 | No OpenTelemetry, alerts or dashboards → OTel spans + OTLP + observability profile (Jaeger, Prometheus, Grafana), versioned dashboard, alert rules, screenshots | FB2, V7-I, V6 10, SELF | 11 | RESOLVIDO | telemetry.py + observability profile; docs/evidence/observability (Jaeger 33 spans with the API trace_id, Grafana, 7 alert rules) |
| P2 | `/metrics` in Prometheus format | V6 10 | 11 | RESOLVIDO | GET /metrics; tests/test_telemetry.py |
| P3 | No replica strategy → stateless API, optional Postgres with migrations, `--scale api=2`, single Telegram worker | FB2, V7-I | 11 | PARCIAL | --scale api=2 over the shared SQLite volume (DB state, DB-shared signing secret, single Telegram worker); Postgres with migrations NOT delivered (docs/OBSERVABILITY.md) |
| P4 | Two compose files → one file with profiles (cloud, offline, test, observability, tools) | V6 10, SELF | 11 | RESOLVIDO | Single docker-compose.yml with profiles offline/test/observability/tools; docker-compose.ai.yml removed |
| P5 | Ollama always starts in cloud mode → evaluate a light embedding inside the API | V6 10, SELF | 11 | NÃO | Not evaluated in this round; Ollama still serves nomic embeddings in cloud mode |
| P6 | Historical reports in `docs/` that do not reflect the code → `docs/history/` + index | V6 10, SELF | 11 | RESOLVIDO | docs/history/ (header 'Histórico — não reflete o código atual') + docs/README.md |
| P7 | One cloud tool case above the latency target (15.3 s) → measure and optimise | SELF | 11 | RESOLVIDO | Cloud run 2026-11-04: tools 8/8 within 15 s in both rounds (p95 13.89 s warm) |

## Offline (block 12)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| F1 | Offline: 2/12 routes, 41% action; Qwen sends everything to the menu | SELF, FB2 | 12 | NÃO | Measured again: offline (Qwen3 1.7B, LLM mode) route 0.184±0.033 and action 0.462 on heldout_v2 (3 runs); not fixed in this round |
| F2 | Hybrid rejected by a safety false negative → kNN decides route only, never safety; fix the cause, not the case | V6 9, SELF | 12 | NÃO | Not done in this round |
| F3 | Unstable Qwen routing depending on prompt wording | SELF | 12 | NÃO | Not done in this round |
| F4 | False risk alert for a vague message and for "transaction decline error" (regression tests in both modes) | SELF | 12 | NÃO | Not done in this round |
| F5 | Try `qwen3:4b` within 8 GB (measure memory) | V6 9 | 12 | NÃO | qwen3:4b not tried in this round |

## Closing (block 13)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| Z1 | `docs/AUDITORIA_V4_V2.md` (every v2 gap and discount) | V7-J | 13 | RESOLVIDO | docs/AUDITORIA_V4_V2.md |
| Z2 | `docs/RESPOSTAS_ENTREVISTA.md` outside Git | V7-J | 13 | RESOLVIDO | written; listed in .gitignore |
| Z3 | README / TESTING / final report updated; clean clone; local CI | V6 11, V7-J | 13 | RESOLVIDO | README/TESTING/EVIDENCE refreshed (d9ce8f3); clean clone: 357 backend tests pass, frontend npm ci + build OK |
| Z4 | New simulation in the feedback v2 format + push commands (wait for authorization) | V7-J | 13 | RESOLVIDO | simulation written outside Git (docs/SIMULACAO_*); push commands shown, awaiting authorization |
| Z5 | Video not recorded (outside scope, recorded here as a risk) | FB2, SELF | — | NÃO (fora do escopo) | |
| Z6 | Any new problem found during the work | SELF | nearest block | — | |
