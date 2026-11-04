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
| K1 | Corpus is 26 hand-written summaries of 10 pages; does not ingest `getnet.net/en` | V6, FB2, SELF | 1 | ABERTO | |
| K2 | Crawler never run; fixed 40-page limit | V6 | 1 | ABERTO | |
| K3 | Discovery via robots → sitemap → WP REST → links; JS pages; politeness; generic User-Agent | V6 1.1 | 1 | ABERTO | |
| K4 | Boilerplate removal, heading-based chunking, rich metadata, dedup | V6 1.2 | 1 | ABERTO | |
| K5 | Versioned snapshot + manifest; precomputed embeddings; offline boot; idempotent refresh command | V6 1.3 | 1 | ABERTO | |
| K6 | Hand-written summaries removed or down-weighted (`curated_summary`), with justification | V6 1.3 | 1 | ABERTO | |
| K7 | Web search inside the Knowledge Agent (tools chosen by the LLM) | V6 1.4, SELF | 1 | ABERTO | |
| K8 | DuckDuckGo scraping is fragile → stable sources (Wikipedia REST / DDG Instant Answer / optional key) | V6 1.4, SELF | 1 | ABERTO | |
| K9 | FX without a tool call → degraded answer (regression) | SELF | 1 | ABERTO | |
| K10 | Retrieval metric was recall@5 on 5 cases → ≥60 labelled questions; recall@1/3/5, MRR, abstention; old × new corpus; BM25 × dense × hybrid | V6 1.5, FB2 | 1 | ABERTO | |

## HITL (block 2)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| H1 | Simulated queue (`real_agent_connected=false`), no operator channel | FB2, V6 7, SELF | 2 | ABERTO | |
| H2 | Telegram channel: card with LLM summary, inline buttons, reply / `/r`, long-polling worker, authorized operators, audit | V7-A | 2 | ABERTO | |
| H3 | Web operator console (queue, details, claim, reply, resolve) with individual login | V7-A, V6 7 | 2 | ABERTO | |
| H4 | Resumption: operator messages reach the customer live; customer talks to the human while `in_progress`; resolution summary in history; "return to AI with instruction" | V7-A, FB2 | 2 | ABERTO | |
| H5 | `real_agent_connected` reflects reality | V7-A | 2 | ABERTO | |
| H6 | Tests: simulated Telegram transport, unauthorized operator, Telegram outage → console works; end-to-end resumption; Playwright customer + operator | V7-A | 2 | ABERTO | |
| H7 | Committed evidence: real transcript + Telegram screenshots + trace | V7-A | 2 | ABERTO | |

## Answer quality and Critic (block 3)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| Q1 | No answer-quality measure (judge, groundedness, number check) | FB2, V7-B, V6 4 | 3 | ABERTO | |
| Q2 | Quality set ≥60 with `must_include`/`must_not_include`/sources/values | V7-B | 3 | ABERTO | |
| Q3 | Metrics: groundedness (judge + deterministic), number accuracy, coverage, correct citation, language, abstention, usefulness 1–5 | V7-B | 3 | ABERTO | |
| Q4 | LLM-as-judge with a versioned rubric, documented judge model, temperature 0, cost | V7-B | 3 | ABERTO | |
| Q5 | Human labels: ~80 answers (incl. injected bad ones) + labelling tool; Critic/judge P/R/F1, kappa; calibrate on half, report on the other half | V7-B | 3 | ABERTO | |
| Q6 | Critic approved 100% / calibration 21%→0% between runs: explain and measure | FB2, SELF, V6 4 | 3 | ABERTO | |
| Q7 | `heldout_v1` (seen) + `heldout_v2` ≥100 new cases with recorded origin; 3 runs per mode, mean ± sd | V6 4, SELF | 3 | ABERTO | |
| Q8 | `RELATORIO_QUALIDADE_<data>.md` | V7-B | 3 | ABERTO | |

## Orchestration (block 4)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| O1 | Fast path dominant (16/17); multi-specialist in 1 case | FB2, SELF | 4 | ABERTO | |
| O2 | Multi-intent scenarios: Supervisor plans with ≥2 specialists; trace plan → observation → decision | V6 5, V7-C | 4 | ABERTO | |
| O3 | Benchmark ≥60 requests per mode (≥20 multi-intent, ≥10 needing a re-plan) + 10 challenge + 18 acceptance, **no NOT_RUN** | V7-C, FB2 | 4 | ABERTO | |
| O4 | Critic with real traffic + `CRITIC_CHALLENGE_MODE` (off in production): rejection, re-plan, success after re-plan, handoff | V7-C | 4 | ABERTO | |
| O5 | Supervisor of ~800 lines → modules (fast path, planner, replanner, composer) without behaviour change | V6 5, SELF | 4 | ABERTO | |

## Evidence without execution (block 5)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| E1 | Cloud mode not reproduced by the evaluator (no PyPI, executes nothing) | FB2 | 5 | ABERTO | |
| E2 | Real cloud recordings (JSONL with full traces) in `docs/evidence/cloud_runs/` | V7-D | 5 | ABERTO | |
| E3 | `replay` provider (cassette) + replay test in CI without a key | V7-D | 5 | ABERTO | |
| E4 | Evidence page in the README with direct links | V7-D | 5 | ABERTO | |
| E5 | UI screenshot gallery generated by Playwright | V7-D | 5 | ABERTO | |

## Secrets and identity (block 6)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| S1 | API key sent in plain text by message → policy: never distribute a key; evaluator uses their own key or replay/offline; old key revoked (user confirms) | FB2, V7-E | 6 | ABERTO | |
| S2 | Secret scanning in CI (pinned gitleaks) + documented pre-commit hook | V7-E | 6 | ABERTO | |
| S3 | Shared operator key → individual operators (hashed password, roles, expiry, per-operator audit) | FB2, V7-E | 6 | ABERTO | |
| S4 | Rate limiting + lockout on customer and operator login; basic rate limit on `/api/chat` | V7-E, V6 8, SELF | 6 | ABERTO | |
| S5 | Public PINs → explicit `DEMO_MODE`; outside demo, configured secret required and no user listing | V7-E, SELF | 6 | ABERTO | |
| S6 | Per-process `AUTH_SECRET` → required outside demo | V6 8, SELF | 12 | ABERTO | |
| S7 | Injection beyond the prompt: tool allowlist per agent, schema-checked args, output filter for other customers' identifiers, delimited retrieved content; new tests (including injection inside a site page) | V6 8, SELF | 12 | ABERTO | |
| S8 | `SECURITY.md`: threats × controls × tests | V6 8 | 12 | ABERTO | |

## Write tools (block 7)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| T1 | Read-only tools → ≥3 write actions with confirmation, idempotency and audit | FB2, V7-F | 7 | ABERTO | |
| T2 | Session-bound expiring confirmation token; the LLM never executes without it; sensitive action needs reinforced confirmation | V7-F | 7 | ABERTO | |
| T3 | Tests: no confirmation → no action; another session's confirmation rejected; idempotency; audit; Critic checks the described effect | V7-F | 7 | ABERTO | |
| T4 | Few synthetic data → more customers, terminals, sales and declines (existing ones kept) | V6, SELF | 7 | ABERTO | |

## Business and contract (block 8)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| B1 | Home-screen suggestions fall into the menu; a clear Payment Link question asks for clarification | V6 2, SELF | 8 | ABERTO | |
| B2 | `selected_topic` on suggestions; typed suggestions answered by real understanding (pt/en, both modes); Playwright clicks all 4 | V6 2 | 8 | ABERTO | |
| B3 | Literal challenge payload returns 401 → anonymous session; customer data requires login | V6 3, SELF | 8 | ABERTO | |
| B4 | Acceptance scenarios marked `NOT_RUN` in the report | FB2 | 4/8 | ABERTO | |

## Engineering judgment (block 9)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| J1 | Heavy chain without a measure that justifies it → ablation (full, no Critic, no CI, no PolicyGate (safety set only), fast path only, planning only) | FB2, V7-G | 9 | ABERTO | |
| J2 | Simplify what does not pay for itself; `docs/ABLACAO_<data>.md` | V7-G | 9 | ABERTO | |
| J3 | Extensive deterministic policy (risk regex, menus) → justify with numbers (cases decided by each rule) | V6, SELF | 9 | ABERTO | |

## Memory and continuous improvement (block 10)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| M1 | No long-conversation summary → incremental summary + structured session memory; 30-turn test; tokens saved | FB2, V7-H, SELF | 10 | ABERTO | |
| M2 | Improvement loop: refresh, 👍/👎 feedback, validated answers (invalidated by corpus version), knowledge-gap queue promoted only by an operator | V6 6, SELF | 10 | ABERTO | |

## Observability and production (block 11)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| P1 | No OpenTelemetry, alerts or dashboards → OTel spans + OTLP + observability profile (Jaeger, Prometheus, Grafana), versioned dashboard, alert rules, screenshots | FB2, V7-I, V6 10, SELF | 11 | ABERTO | |
| P2 | `/metrics` in Prometheus format | V6 10 | 11 | ABERTO | |
| P3 | No replica strategy → stateless API, optional Postgres with migrations, `--scale api=2`, single Telegram worker | FB2, V7-I | 11 | ABERTO | |
| P4 | Two compose files → one file with profiles (cloud, offline, test, observability, tools) | V6 10, SELF | 11 | ABERTO | |
| P5 | Ollama always starts in cloud mode → evaluate a light embedding inside the API | V6 10, SELF | 11 | ABERTO | |
| P6 | Historical reports in `docs/` that do not reflect the code → `docs/history/` + index | V6 10, SELF | 11 | ABERTO | |
| P7 | One cloud tool case above the latency target (15.3 s) → measure and optimise | SELF | 11 | ABERTO | |

## Offline (block 12)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| F1 | Offline: 2/12 routes, 41% action; Qwen sends everything to the menu | SELF, FB2 | 12 | ABERTO | |
| F2 | Hybrid rejected by a safety false negative → kNN decides route only, never safety; fix the cause, not the case | V6 9, SELF | 12 | ABERTO | |
| F3 | Unstable Qwen routing depending on prompt wording | SELF | 12 | ABERTO | |
| F4 | False risk alert for a vague message and for "transaction decline error" (regression tests in both modes) | SELF | 12 | ABERTO | |
| F5 | Try `qwen3:4b` within 8 GB (measure memory) | V6 9 | 12 | ABERTO | |

## Closing (block 13)

| # | Item | Source | Block | Status | Evidence |
|---|---|---|---|---|---|
| Z1 | `docs/AUDITORIA_V4_V2.md` (every v2 gap and discount) | V7-J | 13 | ABERTO | |
| Z2 | `docs/RESPOSTAS_ENTREVISTA.md` outside Git | V7-J | 13 | ABERTO | |
| Z3 | README / TESTING / final report updated; clean clone; local CI | V6 11, V7-J | 13 | ABERTO | |
| Z4 | New simulation in the feedback v2 format + push commands (wait for authorization) | V7-J | 13 | ABERTO | |
| Z5 | Video not recorded (outside scope, recorded here as a risk) | FB2, SELF | — | NÃO (fora do escopo) | |
| Z6 | Any new problem found during the work | SELF | nearest block | — | |
