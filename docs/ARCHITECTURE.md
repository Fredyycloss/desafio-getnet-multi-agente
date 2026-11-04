# Architecture and agent contracts

For the overview and the Mermaid diagram, see the [README](../README.md#architecture). This page records contracts and failure handling.

## Provider layer (`backend/app/infra/llm/`)

**Contract.** `LLMProvider.chat(messages, tools, json_schema, max_tokens, temperature, purpose)` returns:

```
{content, tool_calls[{id, function{name, arguments}}], message, usage{prompt_tokens, output_tokens, latency_ms, cost_usd}, provider, model}
```

- Messages use system/user/assistant/tool roles.
- Tools use the `{"type":"function","function":{...}}` schema.
- Errors: `LLMUnavailable`, `LLMTimeout`, `LLMBudgetExceeded`.

**Adapters:**

| Adapter | Details |
|---|---|
| `ollama` | `/api/chat` with tools and a JSON `format`. `think=false`, `keep_alive`, optional `OLLAMA_NUM_THREAD`. Embeddings via `/api/embed`. |
| `anthropic` | Official SDK pinned to 2.3.0, model `claude-haiku-5-5`. Tool calls are mapped to `tool_use`/`tool_result` with ids. Structured output via `output_config.format`. No sampling parameters. Thinking disabled and effort low by default. Cost comes from the configured price per million tokens. Embeddings are delegated to the local Ollama `nomic-embed-text`. |
| `fixture` | Scripted, used only when `LLM_PROVIDER=fixture`, for the browser test. |

**Selection.** `LLM_PROVIDER=auto`: the key gives `anthropic`, otherwise `OLLAMA_ENABLED=true` gives `ollama`, otherwise there is no model (labelled deterministic fallback). `ollama`, `anthropic` and `none` force a mode.

**Budget.** Every call is bounded by the request-wide budget: cloud 30 s, local 150 s, or `REQUEST_LLM_BUDGET_SECONDS`. A call does not start with less than 2 s left.

**Guard.** Agents import only `app.infra.llm`, and a test checks that no agent imports a provider client.

## Turn flow

1. **Session.** FastAPI authenticates the bearer token, checks session ownership and loads 12 messages of history from SQLite.
2. **Gateway.** A secret, token or card number is blocked and stored as a placeholder. An explicit human request becomes a handoff after the context pass.
3. **Context Intelligence.** It returns a compact JSON object of 11 fields, validated by pydantic. The three routing fields are mandatory, and invalid output raises `LLMUnavailable`. Neutral defaults fill the rest of `ContextAssessment`. Two general floors apply: a retracted danger reference → clarify; danger vocabulary the model calls safe without a figurative reading → clarify.
   - **Modes (`CONTEXT_MODE`).**
     - `llm` (default) calls the model every turn.
     - `hybrid` uses a kNN over local embeddings of `intent_examples.json` for clear turns and calls the model on mandatory triggers: danger vocabulary, figurative or retraction marker, possible injection, short history-dependent message, low confidence, margin or similarity.
     - `embedding` never calls the model.
     - The measured comparison and the decision to keep `llm` as default are in the README.
   - **Annotations.** `decided_by`, `embedding_match` and `llm_trigger` are returned in `context_assessment`.
4. **RiskAssessment.** Deterministic hazards from the current message and the user's own history win over the model. Activity idioms are stripped first ("pegando fogo de tanto movimento"). An explicit retraction removes a non-concrete hazard.
5. **PolicyGate.** Order: deterministic hazard → alert; model `critical` → alert; model `potentially_dangerous`/`ambiguous` → **safety menu** (literal hazard first, human last); uncertainty → topic menu; human → handoff; else continue.
6. **Menus.**
   - The options are stored with the assistant turn.
   - Only short replies (≤ 6 words), or the exact label or number, select an option. A longer message is a new request (subject change).
   - Selecting a support topic leads to the specialist's intake question.
7. **Supervisor.**
   - **Fast path:** one routine specialist with confidence ≥ 0.75 (`context_directed_dispatch`).
   - **Planning:** function calling, up to 3 rounds and 4 tools, with observations ≤ 2,500 characters. `FINAL` reuses the specialists' answers.
8. **Critic.**
   - Deterministic checks (secret request, citation exists, grounding of IDs, dates, amounts and statuses), then model review (material problems only, with today's date).
   - On rejection, one re-plan: call one specialist, or rewrite using only observed values, customer-facing only. A second rejection leads to handoff.
9. **Response.** It carries the trace, `stage_timings`, `model_usage`, the Critic verdict, sources, `degraded`/`degraded_reason` and handoff fields. The model rationale is never returned.

## Knowledge base and Knowledge Agent tools

### Ingestion

The knowledge base is built only by the explicit command `python -m app.knowledge.ingest_cli`; see `backend/app/knowledge/`.

1. **Discovery.** `robots.txt` → sitemaps and sub-sitemaps → internal links.
   - **Domains:** `site.getnet.com.br`, plus `www.getnet.net` limited to `/en` (the URL the challenge names) and `/pt`.
   - **Politeness:** respects `robots.txt`; ~1 s pause with jitter; retry with backoff; generic User-Agent; HTTPS and allowlist only; HTML only.
   - **JavaScript pages:** pages that need JavaScript (for example the fee tables) are rendered with the project's Playwright Chromium when run with `--render-js`.
2. **Extraction.**
   - The main content is picked only if it holds the page copy.
   - Navigation, cookie, form and footer blocks are removed, and so is text repeated on many pages of the same host.
   - Chunks follow the headings, with merging and overlap.
   - Each chunk carries metadata: URL, title, section, breadcrumb, language, `fetched_at`, `content_hash`, `source_type=official_web_snapshot`.
   - Exact deduplication uses the normalized hash.
3. **Snapshot.** Versioned in `backend/app/knowledge/snapshots/<date>/`:
   - `chunks.json.gz`;
   - `embeddings.json.gz` (`nomic-embed-text`, `search_document:` prefix, float16);
   - `manifest.json`: URLs discovered, downloaded, skipped and failed with the reason; pages per section; chunks; characters; timings.
   - **Idempotent:** embeddings of unchanged chunks are reused.
4. **Boot.** Offline: `load_documents()` reads the latest snapshot. The 26 hand-written summaries of the previous version are kept only as an evaluation baseline (`corpus.json`, `source_type=curated_summary`) and are not loaded at runtime.

### Retrieval

- BM25 statistics are computed once per language.
- Dense scores come from the precomputed vectors (numpy); only the query is embedded, with the `search_query:` prefix.
- Hybrid score = 0.55·BM25(normalised) + 0.45·cosine, plus a small bonus for words in the title or section.
- Results are filtered by language. Evidence below 0.12 relevance is not used.

### Knowledge Agent tools

The LLM chooses the tools by function calling:

| Tool | What it does |
|---|---|
| `search_getnet_knowledge` | RAG over the snapshot |
| `search_getnet_site_live` | Reads live the official pages that best match the query from the snapshot's URL inventory (allowlist only). Also used automatically when RAG finds nothing relevant. |
| `web_search` | Public web through stable APIs: optional Brave key → Wikipedia REST → DuckDuckGo Instant Answer |
| `get_weather_forecast` | Open-Meteo |
| `get_exchange_rate` | Frankfurter |

- **Answer:** the LLM writes from the evidence (`[n]` citations with URL and section) and the tool results (numbers copied exactly, provider named).
- **Provider down:** the answer says so and invents nothing (`degraded_reason=provider_unavailable`).
- **No tool call:** if the model calls no tool on a weather or FX question, the keyword pick is a marked fallback (`model_selected_no_tool`).
- **Contract change:** web research is no longer a separate Supervisor specialist. The challenge places the web search tool inside the Knowledge Agent. The old name `web_research_specialist` is accepted as an alias of `knowledge_specialist`.

## Specialist result contract

```
{agent, task, answer, evidence[], tool_calls[{tool,args,ok,duration_ms}], sources[], confidence,
 missing_info[], degraded, degraded_reason, duration_ms, trace}
```

`degraded=true` whenever the answer did not come from the normal model path:
- `llm_disabled`, `llm_unavailable`, `llm_timeout`, `llm_budget_exhausted`;
- `model_selected_no_tool`;
- `provider_unavailable`;
- `llm_empty_answer`.

## Data and memory

SQLite lives on the `getnet_data` volume. It holds:
- synthetic customers, terminals and transactions;
- sessions and messages (each session has one owner);
- the embeddings cache;
- tickets and their messages;
- the tool, stage and model audit (`model_audit`: purpose, provider, model, tokens, latency, cost; never message content).

## Failure handling

| Failure | Behaviour |
|---|---|
| Model unavailable or invalid (AI optional) | labelled deterministic fallback, `degraded: true` |
| Model unavailable (`OLLAMA_REQUIRED=true`) | explicit 503, except human/safety paths |
| Budget spent | `deterministic_fallback_llm_budget`, `degraded: true`, HTTP 200 |
| Embeddings unavailable | BM25 only |
| Weather, FX or search provider down | "provider unavailable" answer, no invented value |
| Low retrieval relevance | abstention → topic menu |
| Critic rejects twice | human handoff with protocol |
| Critical hazard | fixed safety instructions + priority ticket; no specialist runs |
