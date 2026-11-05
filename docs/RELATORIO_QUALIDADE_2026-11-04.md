# Quality report (04/11/2026)

Every number below comes from a committed report produced by a real run. Each line names its file.

## 1. Context decision: held-out v2

- **Dataset.** 109 cases, written without looking at the code, never used for tuning.
- **Runs.** 3 per provider. Values are the mean ± sample standard deviation.
- **Files.** `eval/CONTEXT_EVAL_heldout_v2_{anthropic,ollama}_run{1,2,3}_2026-11-04.json`.

| Metric | Cloud (`claude-haiku-5-5`) | Offline (`qwen3:1.7b`) |
|---|---|---|
| Route accuracy (69 cases) | **0.932 ± 0.008** | 0.184 ± 0.033 |
| Risk accuracy | 0.969 ± 0.005 | 0.856 ± 0.021 |
| Action accuracy | 0.945 ± 0.000 | 0.462 ± 0.059 |
| Clarification F1 | 0.864 ± 0.006 | 0.245 ± 0.020 |
| Safety false negatives | **0** | **0** |
| Safety false-positive rate | 0.037 ± 0.006 | 0.133 ± 0.038 |
| Critical hand-off recall | **1.000** | 0.949 ± 0.089 |
| Cost of the 3 runs | US$0.084 | — |

- **Offline routing is weak.** With the 1.7B model, routing is weak, but safety holds: no dangerous case was missed, because the deterministic RiskAssessment and the PolicyGate do not depend on the model.
- **Not done.** The planned offline redesign (kNN routing, `qwen3:4b`) was not done (checklist F1–F5).

## 2. Answer quality

**Set.** 63 items: 58 answers and 5 cases where the right answer is to abstain.

| Metric | Run with judge (03/11, commit `6694a15`) | Ablation "full" (04/11, commit `861ada7`, no judge) |
|---|---|---|
| Fact coverage (mean) | 0.798 | 0.825 |
| Every number in the evidence | 0.948 | 0.966 |
| Correct citations | 0.889 | 0.857 |
| Correct abstention (n=5) | 1.0 | 0.8 |
| Forbidden content absent | 1.0 | 1.0 |
| Judge: correct | 0.587 | — |
| Judge: grounded | 0.683 | — |
| Judge: usefulness (1–5) | 3.73 | — |
| Mean latency | 7.5 s | 6.0 s |

- **Judge.** `claude-sonnet-5-5`, rubric in `evaluation/`. It was stricter than the deterministic checks: 59% judged fully correct.
- **Judge not yet calibrated.** It has not been checked against human labels (checklist Q5/Q6).
- **Files.** `eval/ANSWER_QUALITY_cloud_run1_2026-11-03.json` and `eval/ABLATION_2026-11-04.json`.

## 3. What each stage contributes

See [`ABLACAO_2026-11-04.md`](ABLACAO_2026-11-04.md):
- the PolicyGate prevents all 19 safety misses;
- Context Intelligence prevents 4 safety misses and makes turns cheaper and faster;
- the Critic raises grounded answers from 52/58 to 56/58.

## 4. Session memory

See `eval/MEMORY_EVAL_2026-11-04.json` and the "Session memory" section of the README.

- **Bug found by the first run.** The memory note was cut by the history window before it reached the specialists.
- **Fixed and re-measured.** The README reports the re-measured numbers.

## Known gaps

- Inline citations are lost in planning mode (see the ablation report).
- The judge is not calibrated against humans.
- Offline routing is weak.
