"""Customer-support tools backed by the repository's synthetic SQLite data."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..clock import today as clock_today
from ..infra.database import Database


def get_customer_profile(db: Database, user_id: str) -> dict:
    customer = db.get_customer(user_id)
    if not customer:
        return {"ok": False, "tool": "get_customer_profile", "error": "demo_customer_not_found", "message": "No demo customer record exists for this user_id."}
    return {"ok": True, "tool": "get_customer_profile", "data": customer, "data_environment": "synthetic_demo"}


def get_terminal_status(db: Database, user_id: str) -> dict:
    terminal = db.get_terminal(user_id)
    if not terminal:
        return {"ok": False, "tool": "get_terminal_status", "error": "demo_terminal_not_found", "message": "No demo terminal is associated with this user_id."}
    return {"ok": True, "tool": "get_terminal_status", "data": terminal, "data_environment": "synthetic_demo"}


def lookup_payment_status(db: Database, user_id: str, period: str = "yesterday") -> dict:
    today = clock_today()
    day = (today - timedelta(days=1)).isoformat() if period in {"yesterday", "ontem"} else today.isoformat()
    customer = db.get_customer(user_id)
    if not customer:
        return {"ok": False, "tool": "lookup_payment_status", "error": "demo_customer_not_found", "user_id": user_id, "message": "No demo customer record exists for this user_id."}
    rows = db.get_transactions(user_id, day=day, status="approved")
    if not rows:
        return {"ok": True, "tool": "lookup_payment_status", "user_id": user_id, "transaction_date": day, "transactions": [], "message": "No approved demo transactions were found for that date.", "data_environment": "synthetic_demo"}
    total = round(sum(item["net_amount"] for item in rows), 2)
    dates = sorted({item["settlement_date"] for item in rows if item["settlement_date"]})
    return {
        "ok": True, "tool": "lookup_payment_status", "user_id": user_id,
        "transaction_date": day, "approved_count": len(rows), "net_total_brl": total,
        "settlement_dates": dates, "transactions": rows, "data_environment": "synthetic_demo",
        "message": "These are synthetic seeded demo records, not real Getnet account or settlement data.",
    }


def find_declined_transactions(db: Database, user_id: str, period: str = "yesterday") -> dict:
    day = (clock_today() - timedelta(days=1)).isoformat() if period in {"yesterday", "ontem"} else clock_today().isoformat()
    customer = db.get_customer(user_id)
    if not customer:
        return {"ok": False, "tool": "find_declined_transactions", "error": "demo_customer_not_found", "user_id": user_id}
    rows = db.get_transactions(user_id, day=day, status="declined")
    return {"ok": True, "tool": "find_declined_transactions", "user_id": user_id, "transaction_date": day, "transactions": rows, "data_environment": "synthetic_demo"}
