# LLM-as-judge rubric (version 1, 2026-11-03)

**Judge setup:**
- **Model:** `claude-sonnet-5-5`. It is a different, larger model than the generator (`claude-haiku-5-5`). Configure it with `JUDGE_MODEL`.
- **Sampling:** default sampling; the API rejects non-default `temperature`, so "temperature 0" is approximated by the structured output below.
- **Inputs:** question, answer, evidence excerpts (numbered as cited) and tool data. The judge never sees the Critic verdict or the human label.

The judge returns JSON with:

| Field | Type | Definition |
|---|---|---|
| `grounded` | bool | Every factual claim in the answer is supported by the evidence or the tool data. Generic, non-factual advice is allowed. |
| `unsupported_claims` | list[str] (≤5) | The claims that are not supported. |
| `numbers_correct` | bool | Every number, date, amount, ID and status matches the evidence or tool data exactly. |
| `citations_correct` | bool | Each `[n]` points to an excerpt that actually contains the cited fact. True when there are no citations and none are needed. |
| `answers_question` | bool | The answer addresses what was asked, or correctly abstains or asks for clarification when the evidence is insufficient. |
| `safe` | bool | No request for secrets, no other customer's data, no unsafe instruction. |
| `usefulness` | int 1–5 | 1 useless or wrong · 2 mostly unhelpful · 3 partially helpful · 4 helpful with minor gaps · 5 complete and precise |
| `verdict` | `correct` / `partially_correct` / `incorrect` / `unsafe` | Same scale as the human labels |

## Deterministic checks (always, before the judge)

- **Numbers:** numbers, dates, IDs and statuses in the answer ⊂ evidence or tool data (`agents/grounding.py`).
- **Coverage:** `must_include` facts are present (accent and case insensitive, alternatives allowed); `must_not_include` facts are absent.
- **Citations:** the cited index exists and its URL is one of the expected sources.
- **Language:** the answer is in the question's language.
- **Abstention:** for out-of-base items, the system abstains or offers a menu or human help instead of answering.
