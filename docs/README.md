# Documentation index

Current documents describe the code in this repository. Reports from earlier versions live in [`history/`](history/), each marked "histórico — não reflete o código atual".

## Start here

| Document | Content |
|---|---|
| [`../README.md`](../README.md) | What the system does, how to run each mode, measured results |
| [`EVIDENCE.md`](EVIDENCE.md) | Everything measured, with links: recorded cloud run, replay, reports, screenshots |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Agents, orchestration (fast path / planning / re-plan), knowledge pipeline, providers |

## Topics

| Document | Content |
|---|---|
| [`SECURITY.md`](SECURITY.md) | Credential policy, identity (demo / non-demo), lockout, anonymous chat, prompt injection, operators |
| [`HITL.md`](HITL.md) | Human hand-off: ticket states, operator console, Telegram, resumption by the AI |
| [`WRITE_ACTIONS.md`](WRITE_ACTIONS.md) | Write tools with confirmation, idempotency and audit |
| [`EVALUATION.md`](EVALUATION.md) | Datasets (dev / held-out v1 / held-out v2), metrics, how to run each evaluation |
| [`TESTING.md`](TESTING.md) | Unit, API, replay and browser tests |
| [`INVENTARIO_TEMPLATES.md`](INVENTARIO_TEMPLATES.md) | Every fixed text and why it is allowed |
| [`OBSERVABILITY.md`](OBSERVABILITY.md) | Traces (OpenTelemetry → Jaeger), metrics (Prometheus), dashboard, alerts, replicas |
| [`MANUAL_ACCEPTANCE_TESTS.md`](MANUAL_ACCEPTANCE_TESTS.md) | Manual walkthrough of the acceptance scenarios |
| [`VIDEO_WALKTHROUGH.md`](VIDEO_WALKTHROUGH.md) | Script for the demo video |
| [`CHECKLIST_V7.md`](CHECKLIST_V7.md) | Every open item from the reviews, with status and evidence |

## Data and reports

- [`eval/`](eval/) holds the evaluation reports: context, retrieval, answer quality, ablation, memory.
- `RELATORIO_LATENCIA_<date>_<label>.json` files are the latency and acceptance benchmarks, from `scripts/benchmark_latency.py`.
- [`evidence/`](evidence/) holds the recorded cloud runs, the UI and observability screenshots, and the HITL screenshots.
- [`evaluation/`](evaluation/) holds the judge rubric, the human-labelling items and the labels.
