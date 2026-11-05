# Audit: v2 feedback → current state (04/11/2026)

Item by item, with source, status and evidence: [`CHECKLIST_V7.md`](CHECKLIST_V7.md). This page groups the points of the v2 feedback by its discounts.

| v2 feedback point | Current state | Evidence |
|---|---|---|
| Cloud mode not reproduced; evaluator executes nothing | **Resolved.** Committed cloud recordings (92 turns, 418 model calls), replay without a key in CI (53/53 same outcome), UI and observability screenshots | [`EVIDENCE.md`](EVIDENCE.md) |
| Key sent in plain text | **Resolved.** No key is ever distributed; own key, replay or offline; gitleaks in CI and pre-commit. The emailed key was revoked (confirmed 04/11/2026) | [`SECURITY.md`](SECURITY.md), checklist S1 |
| Fast path dominant; multi-specialist barely exercised | **Resolved.** 20/20 multi-intent cases call every expected specialist; planning in 18 of 40 orchestration requests | `RELATORIO_LATENCIA_2026-11-04_cloud-v7.json` |
| Critic approves 100% / 21%→0% unexplained | **Resolved in practice.** Challenge mode: 10/10 bad drafts caught, 10/10 fixed by the re-plan, 0 leaked. Severity per issue decided by code. **Pending:** calibration against human labels | checklist Q5/Q6 |
| No answer-quality measure | **Resolved.** 63-item set, deterministic checks, judge rubric; ablation per configuration | `eval/ANSWER_QUALITY_*`, `eval/ABLATION_2026-11-04.json` |
| Heavy chain without justification | **Resolved.** Ablation: without the PolicyGate 19/19 dangerous cases are missed; without Context Intelligence 4 are missed and turns cost 50% more; without the Critic, grounded answers drop 56/58 → 52/58 | [`ABLACAO_2026-11-04.md`](ABLACAO_2026-11-04.md) |
| Shared operator key, public PINs, no lockout | **Resolved.** Individual operators, `DEMO_MODE`, lockout and rate limits | `test_login_security.py` |
| Read-only tools | **Resolved.** 4 write actions with confirmation, idempotency and audit | [`WRITE_ACTIONS.md`](WRITE_ACTIONS.md) |
| No long-conversation summary | **Partial.** Session memory + `recall_conversation`; early-fact recall 2/4 on vs 0/4 off; two misses open | `eval/MEMORY_EVAL_2026-11-04.json` |
| No OTel, alerts, dashboards or replicas | **Resolved** except Postgres: OTel → Jaeger, Prometheus `/metrics`, Grafana, 7 alerts, `--scale api=2` on SQLite | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Literal payload returns 401; home suggestions fall into the menu | **Resolved.** Anonymous session (21/21 checks); suggestions 12/12 in cloud | `RELATORIO_LATENCIA_2026-11-04_cloud-v7-block8.json` |
| Telegram not demonstrated | **Pending.** Code and tests done; the transcript needs the author's bot token | checklist H7 |
| Offline mode weak | **Still open.** heldout_v2 route 0.184±0.033 with Qwen3 1.7B, 0 safety false negatives. The kNN-route redesign and `qwen3:4b` were not done in this round | checklist F1–F5 |

**Not in scope:** the demo video (Z5).
