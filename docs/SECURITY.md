# Security, privacy and operational boundaries

## Identity: demo login with HMAC tokens

- **Login.** `POST /api/auth/demo-login {user_id, pin}` returns a bearer token: a JSON payload (`sub`, `iat`, `exp`) signed with HMAC-SHA256.
  - The secret is `AUTH_SECRET`. When it is empty, a random secret is generated per API process, so tokens stop working after a restart.
  - The expiry is `AUTH_TOKEN_TTL_SECONDS` (default 3600).
- **Demo accounts.** The synthetic users and their PINs are listed in `backend/app/auth.py` and by `GET /api/auth/demo-users`. They are public on purpose.
- **Protected endpoints.**
  - These four require `Authorization: Bearer` and use the **token's** `user_id`:
    - `POST /api/chat`
    - `GET /api/sessions/{id}/messages`
    - `GET /api/handoffs/{protocol}`
    - `POST /api/handoffs/{protocol}/messages`
  - The body keeps `message` + `user_id`, as the challenge contract requires.
  - A `user_id` that differs from the token returns **403**. A missing, tampered or expired token returns **401**.
  - Another customer's session or protocol returns **404**, so its existence is not revealed.
- **Tools.** They never accept `user_id` from the model. Closures bind the authenticated id, and SQL is parameterized.
- **Tests.** `backend/tests/test_auth_and_isolation.py` covers A × B data, session, protocol and "show customer X's sales", token tampering and expiry, and a model that passes another `user_id` to a payment tool.

This scheme is demonstration identity, not production authentication. It has no rate limiting or lockout, and the PINs are public.

## LLM provider keys

- The cloud key is read only from `GETNET_ANTHROPIC_API_KEY`; `ANTHROPIC_API_KEY` is ignored.
- It is passed explicitly to the SDK client and is not kept in any object the API returns. `repr()` of the provider omits it.
- It is never logged, traced, persisted or returned. `test_api_key_never_appears_in_logs_responses_or_metrics` checks the logs, the `/api/health`, `/api/chat` and `/api/metrics` responses, and the SQLite file.
- `.env` is git-ignored; `.env.example` has the field empty.

## Prompt injection

- **Untrusted data.** User messages, history, retrieved documents and tool results are passed to models as data, and every prompt says they are untrusted.
- **Context Intelligence.** Its prompt tells it to ignore instructions that try to set fields or reveal other customers' data. Deterministic hazards and explicit human requests have higher authority than the model.
- **Critic, without a model.** It rejects answers that ask the customer for a password, PIN, CVV, card number or token (an obeyed injection), and citations to sources that do not exist.
- **Tests.** Injection in the message is covered by `test_b_asking_for_a_data_or_injecting_instructions_leaks_nothing` and benchmark scenario A14. Injection inside a RAG document is covered by `test_rag_document_text_is_sent_as_data_not_as_instructions` and `test_critic_rejects_an_answer_that_obeyed_an_injected_document`.
- **Limit.** No prompt guard detects every adversarial input, so treat model answers as fallible.

## Sensitive data

The gateway blocks passwords, tokens and full card numbers before any model sees them, and stores a placeholder instead. Ticket text is redacted for email, card and credential patterns.

## Operator API

The operator API is disabled unless `OPERATOR_API_KEY` is set. It needs `X-Operator-Key` + `X-Operator-ID`, and only the operator who claimed a ticket can reply to it or resolve it. It is a shared demo secret, not enterprise identity.

## Physical safety

- Fire, smoke, sparks, explosion, electric shock, overheating, burning smell and swollen batteries trigger fixed safety instructions (call 193 in Brazil) and a priority protocol. This is deterministic.
- Possible danger the regex does not recognise gets a menu whose first option is "there is a real physical risk".
- The chatbot is not an emergency service.

## Production checklist

Before any real deployment, add:
- real identity (OAuth/SSO) and tenant authorization;
- approved Getnet integrations;
- a secrets manager;
- rate limiting and abuse detection;
- a retention policy and privacy/legal review;
- operator RBAC and notifications;
- monitoring and alerting;
- continuous model and retrieval evaluation and prompt-injection red-teaming;
- dependency and image scanning;
- TLS;
- backups.
