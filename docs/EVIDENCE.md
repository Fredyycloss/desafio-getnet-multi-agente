# Evidence (no execution needed)

Every number on this page comes from a file committed in this repository. Each item says how it was produced and how to reproduce it.

## 1. Recorded cloud run: 04/11/2026, `claude-haiku-5-5`, code at `eac1d96`

Folder: [`evidence/cloud_runs/2026-11-04/`](evidence/cloud_runs/2026-11-04/)

| File | Content |
|---|---|
| [`turns.jsonl`](evidence/cloud_runs/2026-11-04/turns.jsonl) | One line per `/api/chat` call (92: 91 measured plus 1 warm-up). Each line has the scenario, the question, HTTP status, latency, and the **full response**: answer, sources, trace, stage timings, specialist observations with tool arguments and results, Critic verdict and `model_usage` (tokens, cost) |
| [`cassette.jsonl.gz`](evidence/cloud_runs/2026-11-04/cassette.jsonl.gz) | Every model call: 418 chat calls plus embeddings, each with purpose, the messages sent, tool names, the response and tokens. Used by the replay |
| [`manifest.json`](evidence/cloud_runs/2026-11-04/manifest.json) | Commit, model, calls per purpose, tokens (639,784 prompt / 69,427 output), cost **US$ 0.0987** for the whole run |
| [`benchmark_report.json`](evidence/cloud_runs/2026-11-04/benchmark_report.json) | Same file as [`RELATORIO_LATENCIA_2026-11-04_cloud-v7.json`](RELATORIO_LATENCIA_2026-11-04_cloud-v7.json) |

**Privacy.** Only synthetic demo customers appear. Before export, `scripts/export_cloud_run.py` scans for the Anthropic key prefix, bearer tokens, the Telegram token shape and the values of the configured secrets, compared only and never printed. The export is refused on any hit.

### What the run shows

**Latency set.** 10 challenge messages and 7 dossier messages, each in a cold and a warm round:

| Round | Complete model answers | Right specialist | Mean | p95 | Model calls/turn | Critic rejections |
|---|---|---|---|---|---|---|
| cold | 17/17 | 12/12 | 5.83 s | 11.52 s | 4.06 | 0% |
| warm | 17/17 | 12/12 | 5.51 s | 13.74 s | 3.94 | 0% |

**Orchestration (40 requests):** 22 used the fast path and 18 the planning loop.

| Set | n | Result |
|---|---|---|
| Multi-intent: each message needs ≥2 specialists | 20 | Every expected specialist called in **20/20**. Planning 90%, re-plan 25%, hand-off **5%** (1 of 20). Mean 13.26 s, p95 16.93 s, 7.85 model calls, US$ 0.0022 per turn |
| Re-plan candidates, no injection | 10 | Critic rejected 1 first draft; the re-plan fixed it; 0 hand-offs |
| Critic challenge: corrupted first draft (test-only header) | 10 | **10/10 caught**, 10/10 fixed by the single re-plan, 0 hand-offs, **0 reached the customer**. By kind: invented number 6/6, wrong citation 2/2, wrong language 1/1, request for a secret 1/1 |

- **Acceptance scenarios 1–18:** all PASS. None is `NOT_RUN`.
- **Scenario 15 (LLM unavailable) in the cloud variant:** the API is recreated with the provider pointing at a closed local port. The answer is a controlled degraded one, the hand-off still works and the error is counted in `/api/metrics`.
- **Remaining limitation:** in 1 multi-intent case (mi09), the deterministic grounding check did not find the number "22" in the observations, so the answer went to a human.

### Before and after (same day, same 91 requests)

Folder: [`evidence/cloud_runs/2026-11-04-pre-fix/`](evidence/cloud_runs/2026-11-04-pre-fix/), with code at `c4063da` and report [`RELATORIO_LATENCIA_2026-11-04_cloud-v7-pre-fix.json`](RELATORIO_LATENCIA_2026-11-04_cloud-v7-pre-fix.json).

The first run found three defects, fixed in `eac1d96`:
- the model Critic rejected answers whose issues it called "minor";
- Payments records were cut from the Critic's evidence;
- the status check flagged generic wording.

| | before | after |
|---|---|---|
| Multi-intent answers sent to a human | 45% | 5% |
| Multi-intent re-plans | 60% | 25% |
| Challenge drafts fixed by the re-plan | 80% | 100% |
| Warm-round Critic rejections | 14.3% | 0% |

## 2. Replay without a key

`LLM_PROVIDER=replay` serves the recorded model answers. Everything else runs for real: retrieval over the snapshot, SQLite tools, PolicyGate, the deterministic Critic checks, auth and persistence.

- **Matching.** The calls of the recorded request (same `X-Request-ID`) are served in their recorded order. If that fails, the replay falls back to a masked key, then to a loose key. An unrecorded call raises `replay_miss` and the request takes the degraded path. Replay never invents an answer.
- **CI test.** `backend/tests/test_replay_cassette.py` replays 53 single-turn requests from the run. **53/53 give the same outcome** (same specialists, hand-off and Critic verdict), with **0 misses**.
  - 5 requests that used live public providers (weather, exchange rate) are excluded, because their results change between runs.
  - The test freezes the recording date (`DEMO_TODAY`) and restores the terminal state the run observed.
- **Run it yourself:**

```bash
cd backend && PYTHONPATH=. python -m pytest -q -rs tests/test_replay_cassette.py
# or the whole API on the recording:
LLM_PROVIDER=replay DEMO_TODAY=2026-11-04 PYTHONPATH=. uvicorn app.main:app --port 8000
```

## 3. Other measurements

| Evidence | File | Produced by |
|---|---|---|
| Context Intelligence on heldout_v2 (109 cases with recorded origin, never used for tuning), cloud, 3 runs | [`eval/CONTEXT_EVAL_heldout_v2_anthropic_run1_2026-11-04.json`](eval/CONTEXT_EVAL_heldout_v2_anthropic_run1_2026-11-04.json), [run2](eval/CONTEXT_EVAL_heldout_v2_anthropic_run2_2026-11-04.json), [run3](eval/CONTEXT_EVAL_heldout_v2_anthropic_run3_2026-11-04.json) | `python -m app.evaluation.run_context_eval --split heldout_v2 --run N` |
| Same, offline Qwen3 1.7B, 3 runs | [`run1`](eval/CONTEXT_EVAL_heldout_v2_ollama_run1_2026-11-04.json), [run2](eval/CONTEXT_EVAL_heldout_v2_ollama_run2_2026-11-04.json), [run3](eval/CONTEXT_EVAL_heldout_v2_ollama_run3_2026-11-04.json) | same command, `LLM_PROVIDER=ollama` |
| Retrieval: 70 questions, hybrid vs BM25 vs dense vs legacy corpus | [`eval/RETRIEVAL_EVAL_2026-11-03.json`](eval/RETRIEVAL_EVAL_2026-11-03.json) | `python -m app.evaluation.run_retrieval_eval` |
| Answer quality, cloud: 63 questions + LLM judge | [`eval/ANSWER_QUALITY_cloud_run1_2026-11-03.json`](eval/ANSWER_QUALITY_cloud_run1_2026-11-03.json) | `python -m app.evaluation.run_answer_quality` |
| Ablation: quality, safety and routing with the Critic, Context Intelligence, PolicyGate, fast path or planning switched off (cloud, commit `861ada7`) | [`eval/ABLATION_2026-11-04.json`](eval/ABLATION_2026-11-04.json), decisions in [`ABLACAO_2026-11-04.md`](ABLACAO_2026-11-04.md) | `python -m app.evaluation.run_ablation` |
| Session memory on vs off: 4 conversations of 16 turns, recall of early facts, prompt tokens | [`eval/MEMORY_EVAL_2026-11-04.json`](eval/MEMORY_EVAL_2026-11-04.json) | `python -m app.evaluation.run_memory_eval` |
| Quality summary (context mean ± sd, answer quality, stage contributions) | [`RELATORIO_QUALIDADE_2026-11-04.md`](RELATORIO_QUALIDADE_2026-11-04.md) | — |
| Critic and judge vs 83 human labels (calibration / test halves, injected defects) | [`eval/CRITIC_CALIBRATION_2026-11-04.json`](eval/CRITIC_CALIBRATION_2026-11-04.json) | `python -m app.evaluation.calibrate_critic` |

## 4. Screenshots

- **UI gallery** ([`evidence/ui/`](evidence/ui/)). Generated by Playwright over the replayed cloud run, so the answers on screen are the recorded cloud answers:

| | |
|---|---|
| [Login](evidence/ui/01-login.png) | [Home](evidence/ui/02-home.png) |
| [Product answer with sources](evidence/ui/03-product-answer-with-sources.png) | [Customer data from a tool](evidence/ui/04-customer-data-tool-answer.png) |
| [Ambiguous message → menu](evidence/ui/05-ambiguous-clarification-menu.png) | [Physical risk → safety + protocol](evidence/ui/06-physical-risk-safety-handoff.png) |
| [Figurative language](evidence/ui/07-figurative-language.png) | [Operator console](evidence/ui/08-operator-console-queue.png) |

  To regenerate it:

```bash
cd frontend && E2E_PYTHON=../backend/.venv/bin/python E2E_GALLERY=1 E2E_LLM_PROVIDER=replay \
  E2E_REPLAY_DIR=$PWD/../docs/evidence/cloud_runs/2026-11-04 E2E_DEMO_TODAY=2026-11-04 \
  E2E_EVIDENCE_DIR=$PWD/../docs/evidence/ui npx playwright test ui-gallery
```

- **Human hand-off, customer ↔ operator console** ([`evidence/hitl/`](evidence/hitl/)): the request queued, the operator claims and replies, the reply appears live in the chat, and the resolution summary is shown.
- **Telegram:** the transcript waits for a bot token configured by the author (checklist H7).

## 5. CI

- **Workflow:** [`.github/workflows/build.yml`](../.github/workflows/build.yml), with these jobs:
  - secret scan (gitleaks v8.21.2 over the whole history);
  - backend tests;
  - the replay of the recorded cloud run;
  - challenge evaluation;
  - frontend build;
  - Playwright (fixture provider);
  - container smoke test.
- **Results:** on GitHub Actions for the published commits. Local runs of the same commands are listed in the final report.
