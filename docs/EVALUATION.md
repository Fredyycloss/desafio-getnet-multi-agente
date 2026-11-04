# Evaluation protocol

## 1. Context Intelligence: dev vs held-out

Datasets are in `backend/app/evaluation/`; see [DATASETS.md](../backend/app/evaluation/DATASETS.md).

- `context_scenarios_dev.json` has 24 cases. It was used while developing the prompt and rules, so its scores are optimistic.
- `context_scenarios_heldout.json` has 44 cases written on 2026-11-02 before the prompt rewrite. It is **never** used for tuning prompts, rules, thresholds or examples.

```bash
docker compose exec api python -m app.evaluation.run_context_eval --split heldout --output /tmp/heldout.json
docker compose cp api:/tmp/heldout.json docs/eval/
```

**Metrics:**
- risk and action accuracy, and route accuracy (`expected_agent` vs the first recommended agent);
- safety false-negative rate, plus `safety_misses`: dangerous cases that got neither an alert nor the safety menu;
- clarification precision, recall and F1;
- confusion matrix;
- invalid JSON count;
- mean and p95 latency;
- tokens and cost.

**Gate:** zero safety false negatives, plus risk accuracy, action accuracy and clarification F1 all at least 0.90. Labels are never edited to pass. The only label change is documented in DATASETS.md and follows a PolicyGate contract change.

## 2. End-to-end benchmark (real HTTP, real model)

`scripts/benchmark_latency.py` (standard library only):

```bash
python3 scripts/benchmark_latency.py --label anthropic --rounds warm --warmup
python3 scripts/benchmark_latency.py --label ollama --rounds warm --warmup --llm-down   # D9 stops/starts ollama, never `down`
```

**Scenarios:**
- the 10 challenge questions;
- dossier scenarios D1–D10;
- acceptance scenarios 1–18 (`acceptance_map_1_18` in the report).

Multi-turn scenarios use fixed sessions; isolation uses two demo tokens.

**Classification:** each response is `llm_complete`, `fallback_budget`, `fallback_error` or `http_error`. Latency mean and p95 use `llm_complete` only, and fallbacks are failures.

**Also reported:**
- route correctness and degraded rate;
- Critic reviews, rejection rate and escalations, plus the answered-by-agents rate;
- LLM calls, tokens and cost per turn;
- results by category against the targets (simple ≤ 10 s, tools ≤ 15 s, complex ≤ 25 s).

**Scenario 17** (Critic rejecting) is proven by running the Critic rejection tests inside the benchmark, plus any live rejections observed. A live model cannot be made to fail on purpose without altering the product.

## 3. Deterministic regression

`python -m app.evaluation.run_eval` checks route and retrieval for the 10 challenge questions without a model. It runs in CI.

## 4. Results

See [history/RELATORIO_FINAL_2026-11-02.md](history/RELATORIO_FINAL_2026-11-02.md) and the JSON reports it links.
