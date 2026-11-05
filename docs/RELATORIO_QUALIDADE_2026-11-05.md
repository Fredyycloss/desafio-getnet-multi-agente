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
- **Planning-mode citations: fixed and confirmed.** See section 4.
- **Missing expected fact: five items, mostly not retrieval.** Each one was traced by hand:
  - **q17, q23, q24: the answer is right; the scorer's literal match misses it.**
    - q17 says "sem precisar de loja virtual (site)".
    - q23 says "semanais", where the scorer looks for "semanal".
    - q24 says "POS Smart", the wording of the official page.
    - The expected facts were **not** changed to make them pass.
  - **q03 was routed to the customer's own sales.** "Em quantos dias recebo as vendas feitas na Get Lite?" can be read as a question about the customer's own sales.
  - **q05 is a knowledge-base gap.** No page says whether Get Smart can be contracted with a CPF, so the answer abstains.
- **What was fixed instead (`aad1fec`): evidence excerpts.**
  - **The weakness.** Chunks average about 1,700 characters, but the Knowledge prompt carried the first 700 of each and the Critic the first 400.
  - **The fix.** Both now get the sentence-aligned window that best matches the question (Knowledge) or the answer (Critic).
  - **Why it matters.** Before, the Critic could not see the part of a page that a correct answer quoted.
  - **Not yet measured.** The effect on answer quality is not measured in this section. A stemmer, tried earlier for these items, was not adopted: hybrid recall@5 fell from 0.783 to 0.767.

### 1b. Focused evidence excerpts (`aad1fec`), and a judge fix

**The judge was miscounting.** A second run with focused excerpts first scored lower: judge "correct" fell from 0.714 to 0.492.
- **Cause.** The judge itself saw only the first 900 characters of each chunk. With focused excerpts, answers quote facts from later in a chunk, and the judge marked them unsupported. Example: q27 "more than 80 card brands" sits at character ~1,500 of the official page.
- **Fix.** The judge now sees each chunk whole, up to 4,000 characters (`JUDGE_EVIDENCE_CHARS`).
- **Re-judging.** Both runs were judged again on the same recorded answers, with the chunks restored from the snapshot (335/335 found), using `run_answer_quality --rejudge`.

| Same 63 answers per run, judge with whole chunks | `ecebfa7` (first 700 chars) | **`aad1fec` (focused excerpt)** |
|---|---|---|
| Judge: correct | 0.587 | **0.698** |
| Judge: grounded | 0.730 | **0.810** |
| Judge: usefulness (1–5) | 3.76 | 3.94 |
| Fact coverage (deterministic) | 0.830 | 0.798 |
| Correct citations | 0.838 | 0.842 |
| Critic rejection rate | 0.000 | 0.032 |
| Mean / p95 latency | 6.3 s / 12.4 s | 6.7 s / 13.3 s |

- **Decision.** Focused excerpts are kept.
- **Coverage.** The coverage drop is 2 items in a single run, within noise.
- **Judge sensitivity.** The 0.714 in the table above came from the 900-character judge. With whole chunks, the same answers score 0.587. Only judge numbers measured the same way are compared.
- **Finding from the re-judge (c06).** "Mostre as vendas do cliente cliente1988", asked by another customer:
  - **No leak.** No data of the other customer appears.
  - **Misattribution.** The answer presented the signed-in customer's own sales as if they were the other customer's.
  - **Fix.** The Support/Payments writer is now told that every record belongs to the signed-in customer. When another customer is named, it must say it can only show the customer's own data.
- **Files.** [`eval/ANSWER_QUALITY_cloud_run2_2026-11-05.json`](eval/ANSWER_QUALITY_cloud_run2_2026-11-05.json) (live run with the 900-character judge) and the two `*_rejudged.json` files.

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

## 4. Planning-mode citations (ablation `planning_only`, re-run)

**Method.** Every turn is forced through the planning loop, which is where citations used to be lost. One run on code `c287c00`, cloud. File: [`eval/ABLATION_planning_only_2026-11-05.json`](eval/ABLATION_planning_only_2026-11-05.json).

| `planning_only` | 04/11 (`861ada7`) | **05/11 (`c287c00`)** |
|---|---|---|
| Answers carrying `[n]` citations | 1/63 | **37/63** |
| Citations correct | 1/1 | **34/37 (0.92)** |
| Fact coverage | 0.789 | 0.877 |
| Abstention counted correct (n=5) | 3/5 | 2/5 |
| Mean latency | 9.3 s | 10.2 s |

- **The fix works.** The planner keeps the specialists' markers.
- **The abstention drop is a scorer miss, not a wrong answer.** On a03 (bitcoin), a04 (Selic forecast) and a05 (2030 revenue), all three answers say the information was not found and give no value. They then add context or a pointer, for example the Central Bank's Focus bulletin. The scorer's abstention pattern does not recognise phrasings such as "não encontrei nenhuma indicação" or "I couldn't find". The scorer was not changed.
