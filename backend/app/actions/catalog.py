"""The write actions an agent may PROPOSE. None of them executes without the customer's confirmation.

Each entry: tool schema shown to the model (propose_* only; there is no execute tool), argument
validation against the authenticated customer's own records, the confirmation summary (fixed
text: confirmation menus are allowed fixed text by the README policy), and the executor.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

SUPPLY_ITEMS = {"paper_roll": ("bobina de papel", "paper roll"), "terminal": ("maquininha (troca)", "replacement terminal")}
DISPUTE_REASONS = {
    "not_recognized": ("não reconheço a transação", "I do not recognize the transaction"),
    "declined_wrongly": ("a recusa parece indevida", "the decline looks wrong"),
    "duplicate": ("cobrança em duplicidade", "duplicate charge"),
}


class ActionError(ValueError):
    """Invalid proposal (unknown record, record of another customer, bad argument)."""


@dataclass(frozen=True)
class ActionKind:
    kind: str
    tool: dict
    validate: Callable[[Any, str, dict], dict]
    summary: Callable[[dict, str], str]
    reinforced: bool = False  # sensitive: the customer must type a confirmation phrase


def _terminal(db, user_id: str, terminal_id: str | None) -> dict:
    with db.lock:
        if terminal_id:
            row = db.conn.execute("SELECT terminal_id, model, status FROM terminals WHERE terminal_id=? AND user_id=?",
                                  (terminal_id, user_id)).fetchone()
        else:
            row = db.conn.execute("SELECT terminal_id, model, status FROM terminals WHERE user_id=? ORDER BY terminal_id LIMIT 1",
                                  (user_id,)).fetchone()
    if row is None:
        raise ActionError("terminal_not_found")  # same error for another customer's terminal
    return dict(row)


def _v_visit(db, user_id: str, args: dict) -> dict:
    term = _terminal(db, user_id, args.get("terminal_id"))
    problem = " ".join(str(args.get("problem") or "").split())[:160]
    if len(problem) < 3:
        raise ActionError("problem_required")
    return {"terminal_id": term["terminal_id"], "terminal_model": term["model"], "problem": problem}


def _v_supply(db, user_id: str, args: dict) -> dict:
    item = str(args.get("item") or "")
    if item not in SUPPLY_ITEMS:
        raise ActionError("invalid_item")
    term = _terminal(db, user_id, args.get("terminal_id"))
    try:
        quantity = int(args.get("quantity") or 1)
    except (TypeError, ValueError):
        raise ActionError("invalid_quantity") from None
    limit = 10 if item == "paper_roll" else 1
    if not 1 <= quantity <= limit:
        raise ActionError("invalid_quantity")
    return {"item": item, "quantity": quantity, "terminal_id": term["terminal_id"], "terminal_model": term["model"]}


def _v_dispute(db, user_id: str, args: dict) -> dict:
    reason = str(args.get("reason") or "")
    if reason not in DISPUTE_REASONS:
        raise ActionError("invalid_reason")
    with db.lock:
        row = db.conn.execute("SELECT transaction_id, transaction_date, amount, transaction_status FROM transactions "
                              "WHERE transaction_id=? AND user_id=?", (str(args.get("transaction_id") or ""), user_id)).fetchone()
    if row is None:
        raise ActionError("transaction_not_found")
    return {"transaction_id": row["transaction_id"], "transaction_date": row["transaction_date"], "amount": row["amount"],
            "transaction_status": row["transaction_status"], "reason": reason}


def _v_block(db, user_id: str, args: dict) -> dict:
    term = _terminal(db, user_id, args.get("terminal_id"))
    if term["status"] == "blocked_by_customer":
        raise ActionError("terminal_already_blocked")
    reason = " ".join(str(args.get("reason") or "").split())[:160] or "pedido do cliente"
    return {"terminal_id": term["terminal_id"], "terminal_model": term["model"], "reason": reason}


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _s_visit(a: dict, lang: str) -> str:
    return (f"Abrir chamado técnico com visita para a maquininha {a['terminal_id']} ({a['terminal_model']}). Problema: {a['problem']}."
            if lang == "pt" else
            f"Open a technical ticket with an on-site visit for terminal {a['terminal_id']} ({a['terminal_model']}). Problem: {a['problem']}.")


def _s_supply(a: dict, lang: str) -> str:
    pt, en = SUPPLY_ITEMS[a["item"]]
    return (f"Solicitar {a['quantity']} × {pt} para a maquininha {a['terminal_id']} ({a['terminal_model']})."
            if lang == "pt" else f"Request {a['quantity']} × {en} for terminal {a['terminal_id']} ({a['terminal_model']}).")


def _s_dispute(a: dict, lang: str) -> str:
    pt, en = DISPUTE_REASONS[a["reason"]]
    return (f"Contestar a transação {a['transaction_id']} de {a['transaction_date']} ({_brl(a['amount'])}). Motivo: {pt}."
            if lang == "pt" else
            f"Dispute transaction {a['transaction_id']} of {a['transaction_date']} ({_brl(a['amount'])}). Reason: {en}.")


def _s_block(a: dict, lang: str) -> str:
    return (f"Bloquear temporariamente a maquininha {a['terminal_id']} ({a['terminal_model']}): ela deixará de aceitar vendas até o desbloqueio."
            if lang == "pt" else
            f"Temporarily block terminal {a['terminal_id']} ({a['terminal_model']}): it will stop accepting sales until it is unblocked.")


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties, "required": required}}}


KINDS: dict[str, ActionKind] = {
    "technical_visit": ActionKind("technical_visit", _tool(
        "propose_technical_visit",
        "PROPOSE (not execute) a technical ticket with an on-site visit for the customer's terminal. The customer must confirm.",
        {"terminal_id": {"type": "string"}, "problem": {"type": "string", "description": "short description of the problem"}},
        ["problem"]), _v_visit, _s_visit),
    "supply_request": ActionKind("supply_request", _tool(
        "propose_supply_request",
        "PROPOSE (not execute) sending paper rolls or a replacement terminal. The customer must confirm.",
        {"item": {"type": "string", "enum": sorted(SUPPLY_ITEMS)}, "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
         "terminal_id": {"type": "string"}}, ["item"]), _v_supply, _s_supply),
    "transaction_dispute": ActionKind("transaction_dispute", _tool(
        "propose_transaction_dispute",
        "PROPOSE (not execute) a dispute of one of the customer's transactions (not recognized, wrongly declined, duplicate). "
        "Use the transaction_id from the payment observations. The customer must confirm.",
        {"transaction_id": {"type": "string"}, "reason": {"type": "string", "enum": sorted(DISPUTE_REASONS)}},
        ["transaction_id", "reason"]), _v_dispute, _s_dispute),
    "terminal_block": ActionKind("terminal_block", _tool(
        "propose_terminal_block",
        "PROPOSE (not execute) a temporary block of the customer's terminal (lost or stolen device). Sensitive: the customer "
        "must type a confirmation phrase.",
        {"terminal_id": {"type": "string"}, "reason": {"type": "string"}}, []), _v_block, _s_block, reinforced=True),
}
TOOL_TO_KIND = {k.tool["function"]["name"]: k.kind for k in KINDS.values()}


def canonical_args(args: dict) -> str:
    return json.dumps(args, sort_keys=True, ensure_ascii=False)
