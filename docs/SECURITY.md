# Security, privacy and operational boundaries

## Evaluation credential policy

- **The project never distributes an API key.** Not in the repository, not in documents and not by message.
- To run the cloud mode, the evaluator uses **their own** Anthropic key: `bash scripts/set-api-key.sh` stores it in `.env` with hidden input and never prints it.
- Without a key, two modes need no credential:
  - **replay**: `LLM_PROVIDER=replay` replays the recorded cloud run in [`docs/evidence/cloud_runs/`](evidence/cloud_runs/). Retrieval, tools, PolicyGate and the deterministic Critic checks run for real; only the model text is replayed.
  - **offline**: `bash scripts/start-ai.sh -d` runs the local Qwen model.
- The cloud-mode evidence (questions, answers, sources, full traces, Critic verdicts, token usage) is committed, so the cloud behaviour can be checked without executing anything. See [`docs/EVIDENCE.md`](EVIDENCE.md).
- **Key sent earlier by email.** A key was sent to the evaluator by email on 03/11/2026. That practice is withdrawn, and the author confirmed on 04/11/2026 that the key was revoked.
- **Secret scanning.**
  - CI runs gitleaks v8.21.2 (pinned image `zricethezav/gitleaks:v8.21.2`) over the whole git history, with findings redacted.
  - The same scan is a pre-commit hook: `.pre-commit-config.yaml`; run `pre-commit install` once.

## Identity: demo login with HMAC tokens

- **Login.** `POST /api/auth/demo-login {user_id, pin}` returns a bearer token: a JSON payload (`sub`, `iat`, `exp`) signed with HMAC-SHA256.
  - The secret is `AUTH_SECRET`. When it is empty, a random secret is generated per API process, so tokens stop working after a restart.
  - The expiry is `AUTH_TOKEN_TTL_SECONDS` (default 3600).
- **Demo accounts (`DEMO_MODE=true`, the default for the challenge).** The synthetic users and their PINs are listed in `backend/app/auth.py` and by `GET /api/auth/demo-users`. They are public on purpose.
- **Outside the demo (`DEMO_MODE=false`):**
  - `GET /api/auth/demo-users` returns 404, so no account list is served, and the login screen asks for the user id.
  - The public PINs and the demo operators stop working.
  - Customer credentials come from `CUSTOMER_CREDENTIALS_FILE`: scrypt hashes, created with `python -m app.auth add-customer <id> --file <path>`, with the PIN read without echo.
  - The API refuses to start without `AUTH_SECRET` (at least 32 characters) and without that file.
- **Lockout and rate limiting** (customer and operator login). The counters live in the database, so every API replica shares them.
  - After `LOGIN_MAX_FAILURES` (5) failures within `LOGIN_WINDOW_SECONDS` (300), the account is locked for `LOGIN_LOCKOUT_SECONDS` (300). The API answers 429 with `Retry-After`.
  - One client address is limited to `LOGIN_MAX_REQUESTS_PER_MINUTE` (30) attempts, against password spraying.
  - Unknown and known accounts get the same 401 answer.
  - Tests: `backend/tests/test_login_security.py`.
- **Anonymous chat.** `POST /api/chat` without a token (the literal challenge payload) is an anonymous session.
  - Public knowledge, web information and hand-off work.
  - Customer-data and write tools answer `login_required`; the body `user_id` is never used to read data.
  - Anonymous sessions cannot read or continue a customer's session (404).
- **Protected endpoints.**
  - These require `Authorization: Bearer` and use the **token's** `user_id` (`/api/chat` too, when a token is sent):
    - `GET /api/sessions/{id}/messages`
    - `GET /api/handoffs/{protocol}`
    - `POST /api/handoffs/{protocol}/messages`
  - The body keeps `message` + `user_id`, as the challenge contract requires.
  - A `user_id` that differs from the token returns **403**. A missing, tampered or expired token returns **401**.
  - Another customer's session or protocol returns **404**, so its existence is not revealed.
- **Tools.** They never accept `user_id` from the model. Closures bind the authenticated id, and SQL is parameterized.
- **Tests.** `backend/tests/test_auth_and_isolation.py` covers A × B data, session, protocol and "show customer X's sales", token tampering and expiry, and a model that passes another `user_id` to a payment tool.

In demo mode this is demonstration identity with public PINs, not production authentication.

## LLM provider keys

- The cloud key is read only from `GETNET_ANTHROPIC_API_KEY`; `ANTHROPIC_API_KEY` is ignored.
- It is passed explicitly to the SDK client and is not kept in any object the API returns. `repr()` of the provider omits it.
- It is never logged, traced, persisted or returned. `test_api_key_never_appears_in_logs_responses_or_metrics` checks the logs, the `/api/health`, `/api/chat` and `/api/metrics` responses, and the SQLite file.
- `.env` is git-ignored; `.env.example` has the field empty.
- `scripts/set-api-key.sh` stores the key with hidden input, writing only that line with mode 600 and never echoing it.
- A refused (401/403) or out-of-credit key is reported in `/api/health` → `cloud_status` and as `degraded_reason`, without the key. The SDK error body is classified and never logged.

## Prompt injection

- **Untrusted data.** User messages, history, retrieved documents and tool results are passed to models as data, and every prompt says they are untrusted.
- **Context Intelligence.** Its prompt tells it to ignore instructions that try to set fields or reveal other customers' data. Deterministic hazards and explicit human requests have higher authority than the model.
- **Critic, without a model.** It rejects answers that ask the customer for a password, PIN, CVV, card number or token (an obeyed injection), and citations to sources that do not exist.
- **Tests.** Injection in the message is covered by `test_b_asking_for_a_data_or_injecting_instructions_leaks_nothing` and benchmark scenario A14. Injection inside a RAG document is covered by `test_rag_document_text_is_sent_as_data_not_as_instructions` and `test_critic_rejects_an_answer_that_obeyed_an_injected_document`.
- **Limit.** No prompt guard detects every adversarial input, so treat model answers as fallible.

## Sensitive data

The gateway blocks passwords, tokens and full card numbers before any model sees them, and stores a placeholder instead. Ticket text is redacted for email, card and credential patterns.

## Operator API

- **Individual accounts.** Each operator has an account with a scrypt password hash, compared in constant time; a dummy hash is computed for unknown users.
  - Roles: `operator` and `supervisor`. The supervisor sees the audit log and the knowledge-gap queue.
  - Login: `POST /api/operator/login` returns an HMAC token with `kind=operator` and an expiry (`OPERATOR_TOKEN_TTL_SECONDS`, default 8 h).
- **Accounts.**
  - Demo operators exist only with `DEMO_MODE=true`: `ana.operadora` and `bruno.supervisor`, with passwords in `docs/HITL.md`.
  - Other accounts are created with `python -m app.hitl.operators add <user> --role operator|supervisor`.
- **Audit.** Every action is recorded per operator and channel (console or Telegram): login ok / failed / locked, claim, reply, resolve, return to AI.
- **Ticket ownership.** Only the operator who claimed a ticket can reply to it or resolve it.
- **Shared key.** The shared `X-Operator-Key` exists only for bootstrap, is disabled unless `OPERATOR_API_KEY` is set, and is not used by the console or the Telegram worker.

## Physical safety

- Fire, smoke, sparks, explosion, electric shock, overheating, burning smell and swollen batteries trigger fixed safety instructions (call 193 in Brazil) and a priority protocol. This is deterministic.
- Possible danger the regex does not recognise gets a menu whose first option is "there is a real physical risk".
- The chatbot is not an emergency service.

## Production checklist

Before any real deployment, add:
- real identity (OAuth/SSO) and tenant authorization;
- approved Getnet integrations;
- a secrets manager;
- abuse detection beyond the login limiter;
- a retention policy and privacy/legal review;
- SSO for operators;
- monitoring and alerting;
- continuous model and retrieval evaluation and prompt-injection red-teaming;
- dependency and image scanning;
- TLS;
- backups.

## Threats × controls × tests

| Threat | Control | Test |
|---|---|---|
| Reading another customer's data by changing `user_id` | Identity from the token. Tools bind the server-side id. Identity arguments from the model are dropped | `test_auth_and_isolation.py`, `test_injection_defense.py::test_identity_and_unknown_arguments_are_dropped_and_bad_values_rejected` |
| Literal payload without a token reading data | Anonymous session; customer tools answer `login_required` | `test_anonymous_and_topics.py`, benchmark `B3_anonymous_literal` |
| Leaking another customer's identifiers in an answer | Output filter (`app/output_filter.py`) | `test_injection_defense.py::test_other_customers_identifiers_are_removed_from_the_answer` |
| Prompt injection in the message | Untrusted-data prompts; deterministic Critic (secret requests, missing citations); PolicyGate authority | benchmark `A14_prompt_injection`, `test_auth_and_isolation.py` |
| Prompt injection inside a retrieved page | `<untrusted_data>` delimiters that a page cannot close; the Critic | `test_injection_defense.py::test_retrieved_page_is_delimited_and_cannot_close_the_delimiter`, `test_critic_rejects_an_answer_that_obeyed_an_injected_document` |
| The model calling a tool of another agent, or with bad arguments | Per-agent allowlist; schema check (types, enums, ranges, required) | `test_injection_defense.py` |
| A write action without consent | Only `propose_*` tools; confirmation bound to customer and session, with expiry and token; idempotency; audit | `test_write_actions.py` |
| Brute force or password spraying | Account lockout, per-address ceiling, chat rate limit | `test_login_security.py` |
| Secrets in the repository or in evidence | gitleaks in CI and pre-commit; credential scan before exporting recordings | CI job `secret-scan`, `scripts/export_cloud_run.py` |
| Sensitive data sent to models or memory | Guardrail block before any model; redaction of the summary and gaps | `test_session_memory.py`, guardrail tests |
| Shared operator credential | Individual scrypt accounts, roles, expiry, per-operator audit | `test_hitl_api.py`, `test_login_security.py` |
