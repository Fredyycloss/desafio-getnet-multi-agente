# Write actions with confirmation

The agents can change the synthetic records, but only after the customer explicitly confirms.

| Action | Agent | Tool the model calls | Effect after confirmation |
|---|---|---|---|
| Technical ticket with an on-site visit | Customer Support | `propose_technical_visit` | `service_requests` row, protocol `ACT-…` |
| Paper rolls (1–10) or a replacement terminal | Customer Support | `propose_supply_request` | `service_requests` row |
| Dispute one of the customer's transactions | Payments | `propose_transaction_dispute` | `service_requests` row |
| Temporary terminal block (lost or stolen) | Customer Support | `propose_terminal_block` | terminal status `blocked_by_customer` + `service_requests` row |

## Flow

1. **The model chooses, the code validates.**
   - The model picks the action and its arguments by function calling. Only `propose_*` tools exist; there is no execute tool.
   - The code checks every argument against the authenticated customer's own records. Another customer's terminal or transaction gets the same "not found" as an unknown one.
2. **A pending action is stored.** It is bound to the customer and the conversation, with:
   - an expiry (`ACTION_CONFIRMATION_TTL_SECONDS`, default 600);
   - a one-time confirmation token, which goes only to the client and is never written to the history;
   - an idempotency key (customer + action + arguments).
3. **The customer sees a confirmation menu.**
   - The menu text is fixed and built from the validated record (allowed fixed text: confirmation menus).
   - The Critic's deterministic check confirms that every ID, value and date in that text exists in the record (`action_confirmation_check`).
4. **The customer decides**, in one of two ways:
   - a short "sim"/"yes" or "cancelar"/"cancel" in the same conversation;
   - the Confirm/Cancel buttons, which call `POST /api/actions/{id}/confirm|cancel` with the token and the `session_id`.
   - Any other message goes through the normal pipeline, and the action stays pending until it expires.
5. **Sensitive action.** A terminal block needs the typed phrase `BLOQUEAR <terminal>` (or `BLOCK <terminal>`); a plain "sim" is not enough.
6. **Execution happens exactly once and returns a protocol.**
   - A second confirmation, or the same request later (`ACTION_IDEMPOTENCY_HOURS`, default 24), returns the existing protocol and creates nothing new.
   - The result text is checked by the Critic against the executed record.
7. **Audit.** `action_audit` records each event: proposed, proposal_rejected, superseded, executed, cancelled, expired, repeat_confirmation_ignored, and decision_rejected (other_session, bad_token, typed_phrase_missing). `GET /api/actions` lists the customer's own actions and audit trail.

Tests: `backend/tests/test_write_actions.py` covers these cases:
- nothing executes without confirmation;
- a confirmation from another session, another customer or with a wrong token does not count;
- confirming twice and repeating the request later do not duplicate anything;
- cancel and expiry never execute;
- a dispute only works on the customer's own transactions;
- a block needs the typed phrase;
- there is no execute tool, and the token is not in the history.
