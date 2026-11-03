# Inventory of fixed text and keyword routing

Rule (`docs/MISSAO_AGENTES_REAIS.md`, section 1): product, support, payments and public-research answers are written by an LLM agent from tools/evidence and reviewed by the Critic. Fixed text is allowed only for (1) emergency/physical risk, (2) sensitive-data block, (3) clarification menus and protocol confirmations, (4) explicit fallbacks when the LLM is disabled, unavailable or out of budget — marked `degraded: true` and counted as failures by `scripts/benchmark_latency.py`.

Method: `grep` for answer f-strings/sentences, keyword lists and `if any(token in text ...)` in `backend/app`. State after stage 1.

| Location | What | Category | Decision |
|---|---|---|---|
| `risk_assessment_agent.py` `message_template` | stop-using/193 instructions for hazards | 1 | keep |
| `supervisor_agent.py` safety messages (literal hazard confirmed, ambiguous/possible hazard) | emergency guidance + protocol | 1 + 3 | keep |
| `guardrails.py` | password/token/card block notice; explicit human-request detection | 2 / gateway | keep |
| `clarification.py` (dataset phrases removed from the menu-kind keywords in stage A) | topic menus, unsupported-topic menu question, intake questions after a topic choice | 3 | keep (question may become LLM-written later; options stay fixed) |
| `escalation_agent.py` | "request registered in the simulated queue… protocol" | 3 | keep |
| `support_agent.py` / `payments_agent.py` `compose_template` | account/terminal/sales sentences | 4 | **fallback only**, `degraded=true` (`template_fallback`) |
| `support_agent.py` / `payments_agent.py` `keyword_selection` | tool choice by keywords | 4 | **fallback only** (model disabled/unavailable or chose no tool), `degraded=true` |
| `payments_agent.py` `handles()` | Support vs Payments in the no-LLM router | 4 | fallback router only |
| `web_research_agent.py` `_run_keyword`, `_extract_location`, weather/FX/search f-strings | keyword routing, regex city, template answers | 4 | **fallback only**; model path extracts parameters and writes the answer (`web_template_fallback` / `web_regex_fallback`, `degraded=true`) |
| `web_research_agent.py` `_unavailable` | "provider unavailable, no value invented" | error notice | keep; `degraded=true` (`provider_unavailable`) |
| `knowledge_agent.py` extractive answer | official snippets verbatim | 4 | **fallback only**, `degraded=true` (`extractive_fallback`) |
| `knowledge_agent.py` abstention sentence | "not enough evidence" | 3 | Supervisor replaces it with the topic menu |
| `supervisor_agent.py` greeting | planner's own text; fixed greeting only if the model returned nothing | 4 | fallback marked `degraded` |
| `supervisor_agent.py` "could not complete the analysis safely" | empty draft guard | 4 | keep as guard |
| `router_agent.py` | keyword router | 4 | used only by `_run_fallback` (LLM disabled/unavailable/budget) |
| `context_intelligence.py` `safe_patterns`, `clarify_patterns`, `guarded_explosion_patterns`; dataset phrases in the CI prompt | **evaluation leak** | defect | **removed** (stage A); replaced by two general floors: retracted danger reference → clarify; danger vocabulary the model calls safe without a figurative reading → clarify |
| `risk_assessment_agent.py` `falei que…explodiu…` regex and `loja…pegando fogo…movimento` case | **evaluation leak** | defect | **generalised** (stage A): explicit retraction markers + activity idiom `pegando fogo de tanto (movimento|venda|cliente|gente)` |

Replaced in stages 0–1 (previously the normal path): Web Research keyword routing + f-string answers; Support keyword tool selection + composed answer; Supervisor-written rewrite of every answer; Critic called as a model tool.
