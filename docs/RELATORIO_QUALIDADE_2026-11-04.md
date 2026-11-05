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
- **Judge vs human labels.** It agrees with them at chance level; see section 5.
- **Files.** `eval/ANSWER_QUALITY_cloud_run1_2026-11-03.json` and `eval/ABLATION_2026-11-04.json`.

## 3. What each stage contributes

See [`ABLACAO_2026-11-04.md`](ABLACAO_2026-11-04.md):
- the PolicyGate prevents all 19 safety misses;
- Context Intelligence prevents 4 safety misses and makes turns cheaper and faster;
- the Critic raises grounded answers from 52/58 to 56/58.

## 4. Session memory

**Set.** 4 conversations of 16 turns, cloud. The fact is said in turn 1 and asked in turn 16. Files: `eval/MEMORY_EVAL_2026-11-04.json` and `eval/memory_runs/`.

| Code | Memory on | Memory off |
|---|---|---|
| Before the fix (`861ada7`) | 1/4 | 0/4 |
| History-window fix | 1/4 | 1/4 |
| + `recall_conversation` (`1caa3cd`) | **2/4** | 0/4 |

- **Window fix.** The memory note was cut by the history window before it reached the specialists. The Support/Payments writer received no history at all.
- **Recall tool.** Questions about the conversation itself had no route and ended in a Knowledge abstention.
- **Off column is noise.** The single "off" recall in the middle run came from a terminal tool lookup, not from memory.
- **Still open.** Two of the four recall questions still miss: one goes to a clarification menu, and in the other the recall tool is not chosen.

## 5. Critic and judge against human labels

**Labels.** 83 answers labelled by the author (`evaluation/human_labels.jsonl`):
- 63 real answers and 20 with an injected defect;
- 42 correct, 23 partial, 16 incorrect, 2 unsafe.

**Method.** The split is fixed by a hash of the item id: 44 items to calibrate, 39 to test. The positive class is "should be rejected" (incorrect or unsafe). Code: `calibrate_critic.py`, with `DEMO_TODAY=2026-11-04`, the date the answers were recorded.

Files:
- `eval/CRITIC_CALIBRATION_2026-11-04.json`;
- `eval/critic_calibration_runs/1_without_demo_today.json`, the first run, which had the date wrong.

| Test half (39) | Precision | Recall | F1 | Cohen's kappa |
|---|---|---|---|---|
| Critic `material` (chosen on the calibration half) | 0.18 | 0.30 | 0.22 | −0.15 |
| Critic `strict` | 0.28 | 1.00 | 0.43 | 0.06 |
| Judge (`claude-sonnet-5-5`) | 0.25 | 0.10 | 0.14 | 0.00 |

| Injected defects (20, defect known regardless of labels) | Caught |
|---|---|
| Critic `material` | **18** |
| Critic `strict` | 19 |
| Judge | 8 |
| Human label "not correct" | 9 |

**What this shows:**
- **Low agreement.** The Critic and the judge agree with the human labels at chance level (kappa ≈ 0). That is a negative result.
- **Planted defects.** The Critic catches the defects that were planted in the answers: an invented number, a wrong ID, a wrong citation. On this subset it beats both the judge and the labeller.
- **Different criteria.** Most answers the human rejected and the Critic approved were judged against outside knowledge, while the Critic checks the answer against the retrieved evidence only. Examples:
  - q27: card brands accepted;
  - a03: "does not accept bitcoin";
  - q04: payment modes.

  When the evidence is incomplete, an answer can be fully grounded and still incomplete. That is a retrieval or coverage gap, and the Critic cannot see it.
- **Critic false rejections.** 6 of 83 Critic outputs failed validation. Production treats them as rejections (fail closed), so they count as false rejections. Some date reasoning ("tomorrow", "yesterday") was also wrong.
- **Decision.** `material` is kept, as chosen on the calibration half. `strict` would reject 26 of 29 acceptable test answers.

**Not fixed in this round:**
- the Critic's invalid-output rate (7%);
- its relative-date reasoning;
- a completeness check against the expected facts.

## Known gaps

- Inline citations are lost in planning mode (see the ablation report).
- Memory recall is 2/4 on the long-conversation set.
- Critic and judge agree with the human labels at chance level (kappa ≈ 0); the Critic still catches 18/20 injected defects.
- Offline routing is weak.
