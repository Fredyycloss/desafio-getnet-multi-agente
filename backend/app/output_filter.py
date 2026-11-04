"""Last line of defence against cross-customer leaks: identifiers of OTHER customers are removed
from an answer before it is returned or stored, whatever produced them (model, tool, injection).

Checked identifiers: transactions (TX-...), terminals (TERM-...), attendance protocols (GET-...)
and action protocols (ACT-...). An identifier that exists and belongs to someone else is
replaced; unknown identifiers are left to the Critic (which rejects invented values). For an
anonymous session every customer identifier is foreign.
"""
from __future__ import annotations

import re

PATTERNS = {
    "transactions": (re.compile(r"\bTX-[A-Z0-9-]+\b"), "SELECT user_id FROM transactions WHERE transaction_id=?"),
    "terminals": (re.compile(r"\bTERM-[A-Z0-9-]+\b"), "SELECT user_id FROM terminals WHERE terminal_id=?"),
    "tickets": (re.compile(r"\bGET-\d{8}-[0-9A-F]{6}\b"), "SELECT user_id FROM tickets WHERE protocol=?"),
    "actions": (re.compile(r"\bACT-\d{8}-[0-9A-F]{6}\b"), "SELECT user_id FROM service_requests WHERE protocol=?"),
}


def foreign_identifiers(db, user_id: str, text: str) -> list[str]:
    found = []
    for pattern, query in PATTERNS.values():
        for value in dict.fromkeys(pattern.findall(text or "")):
            try:
                with db.lock:
                    row = db.conn.execute(query, (value,)).fetchone()
            except Exception:  # noqa: BLE001 - table may not exist yet (fresh database)
                row = None
            if row is not None and row[0] != user_id:
                found.append(value)
    return found


def redact_foreign(db, user_id: str, result: dict) -> dict:
    foreign = foreign_identifiers(db, user_id, result.get("answer", ""))
    if not foreign:
        return result
    answer = result["answer"]
    for value in foreign:
        answer = answer.replace(value, "[identificador de outro cliente removido]")
    return {**result, "answer": answer, "trace": [*(result.get("trace") or []), f"output_filter_redacted:{len(foreign)}"]}
