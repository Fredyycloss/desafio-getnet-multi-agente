# Quality report, update (05/11/2026)

**What this is.** The re-measurement after two commits:
- `e971564`: planner keeps citations; Critic retries invalid JSON, gets relative dates and 160 output tokens;
- `ecebfa7`: Knowledge consults session memory before abstaining; memory eval grows to 12 conversations.

**How it was run.** Every number comes from a run on code `ecebfa7`, cloud provider, `claude-haiku-5-5` (judge `claude-sonnet-5-5`). Sections 1–3 of [`RELATORIO_QUALIDADE_2026-11-04.md`](RELATORIO_QUALIDADE_2026-11-04.md) still describe the context eval and the ablation.

## 1. Answer quality (63 items, with judge)

| Metric | 03/11 (`6694a15`) | **05/11 (`ecebfa7`)** |
|---|---|---|
| Fact coverage (mean) | 0.798 | **0.830** |
| Every number in the evidence | 0.948 | 0.931 |
| Correct citations | 0.889 (n=27) | 0.838 (n=37) |
| Correct abstention (n=5) | 1.0 | 1.0 |
| Forbidden content absent | 1.0 | 1.0 |
| Critic rejection rate | 0.111 | 0.000 |
| Judge: correct | 0.587 | **0.714** |
| Judge: grounded | 0.683 | **0.794** |
| Judge: usefulness (1–5) | 3.73 | **3.98** |
| Mean / p95 latency | 7.5 s / — | 6.3 s / 12.4 s |
| Cost per turn | — | US$ 0.0010 |

**Files.**
- [`eval/ANSWER_QUALITY_cloud_2026-11-05.json`](eval/ANSWER_QUALITY_cloud_2026-11-05.json): the run reported above.
- [`eval/answer_quality_runs/1_with_demo_today_after_midnight.json`](eval/answer_quality_runs/1_with_demo_today_after_midnight.json): an invalid run, kept as evidence.

**Why the first 05/11 run is invalid.** It ran with `DEMO_TODAY=2026-11-04` past midnight.
- **What went wrong.** The live data was already dated 05/11: terminal `last_seen_at` and the weather forecast. The Critic was told "today" was 04/11, so it rejected 6 correct answers as future-dated: q18, c07, c09, c10, w02 and w04. They ended in hand-offs.
- **Rule.** `DEMO_TODAY` is only for replaying recorded answers, as the calibration in section 3 does.

**Still open.**
- **Single run.** One run; differences under about 5 points are within noise.
- **Planning-mode citations.** Of the 5 items answered in planning mode, 2 carry citations:
  - 1 is correct;
  - m01 is wrong.

  The fix (`planner_draft_dropped_citations_replaced`) has a unit test but did not trigger in this run. It is not proven on live traffic.
- **Missing expected fact.** Five items still miss their expected fact: q03, q05, q17, q23 and q24. These are the retrieval gaps already listed. A stemmer was tried for them and not adopted, because hybrid recall@5 fell from 0.783 to 0.767.

## 2. Session memory (12 conversations of 16 turns)

**Method.** The fact is said in turn 1 and asked in turn 16.

| Run | Memory on | Memory off |
|---|---|---|
| **Clean run** ([`eval/MEMORY_EVAL_2026-11-05.json`](eval/MEMORY_EVAL_2026-11-05.json)) | **9/12** | 3/12 |
| Run with the frozen-date confound ([`memory_runs/3_…`](eval/memory_runs/3_with_demo_today_after_midnight.json)) | 10/12 | 2/12 |
| 04/11, 4 conversations | 2/4 | 0/4 |

- **What changed.** Before abstaining, the Knowledge Agent now reads the session memory when a memory note exists (trace `no_evidence_recall_conversation`).
- **"Off" hits are inflated by the scorer.** The scorer checks for keywords:
  - two of the three "off" hits (payment_pref_pt, product_interest_en) are answers saying "I don't have that" that happen to contain the keyword;
  - terminal_problem is a real tool lookup.
- **Misses in the clean run:**
  - owner_name_pt and business_type_en were answered from the customer profile, not from memory (both were recalled in the other run);
  - open_days_en went to a clarification menu.
- **Cost.** With memory on, the last turn's prompt is 7,428 tokens against 5,394 off. The summary calls cost US$ 0.026 for the 12 conversations.

## 3. Critic and judge against the 83 human labels

**Method.** Same split and labels as on 04/11, with `DEMO_TODAY=2026-11-04` (the date the answers were recorded). File: [`eval/CRITIC_CALIBRATION_2026-11-05.json`](eval/CRITIC_CALIBRATION_2026-11-05.json).

| | 04/11 | **05/11** |
|---|---|---|
| Invalid Critic outputs (`material`) | 6/83 | **0/83** |
| Test half: Critic `material` F1 / kappa | 0.22 / −0.15 | 0.28 / −0.09 |
| Calibration half: Critic `material` F1 / kappa | 0.38 / 0.18 | 0.36 / 0.13 |
| Test half: judge F1 / kappa | 0.14 / 0.00 | 0.14 / 0.00 |
| Injected defects caught (20): Critic `material` / judge | 18 / 8 | 18 / 8 |

- **Fixed.** The retry removed the invalid outputs. They had counted as false rejections.
- **Not fixed.** Agreement with the human labels is still at chance level. The cause found on 04/11 still holds: the human judged completeness against outside knowledge, while the Critic checks the answer against the retrieved evidence.
- **Next step.** A second labeller would separate labelling noise from Critic error. That depends on a person, not on code.
