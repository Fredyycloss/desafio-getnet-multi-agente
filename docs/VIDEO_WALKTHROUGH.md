# Required video walkthrough (5–7 minutes)

The challenge submission explicitly requests a video. Record a screen walkthrough and replace the link placeholder in the root README before submitting.

## Suggested script

1. **0:00–0:40 — Problem and scope.** Explain the Getnet support use case and state that customer records and operator queue are synthetic demonstration data, not real Getnet integration.
2. **0:40–1:40 — Architecture.** Show the React app, FastAPI API, SQLite, Supervisor Agent and named specialist agents. Explain why the supervisor is not a keyword router when Ollama is enabled.
3. **1:40–2:40 — Tool orchestration.** Open `supervisor_agent.py`; show the function schemas, bounded call loop, tool observations, re-planning and critic gate. Show `/api/agents` and a returned trace.
4. **2:40–3:35 — RAG.** Show the corpus JSON, source metadata, BM25/dense hybrid retrieval, offline snapshot and source citations. Ask Get Lite and compare Get Clássica/Get Smart in PT and EN.
5. **3:35–4:30 — Customer Support.** Ask about yesterday's sales with demo user `cliente1988`; show SQLite tool observations and clarify the figures are synthetic.
6. **4:30–5:20 — Risk and HITL.** Report a terminal explosion/smoke; show critical triage and protocol. Use the protected operator API to claim, reply and resolve the ticket. State that there is no live operator connection.
7. **5:20–6:10 — Research and evaluation.** Ask weather and exchange rate, show sources and provider date. Run pytest and dataset evaluation.
8. **6:10–6:40 — Reliability and limits.** Show Docker Compose, health endpoint, CI Actions. Explain offline fallback, Ollama dependency and what would require approved production integrations.

## What not to claim

- Do not say the project is connected to Getnet production systems.
- Do not say a real human receives tickets.
- Do not describe deterministic fallback as autonomous LLM orchestration.
- Do not claim tests prove live LLM answer quality; they validate deterministic code paths and tool-loop wiring.
