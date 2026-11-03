from datetime import date, timedelta

from app.agents.support_tools import (
    find_declined_transactions,
    get_customer_profile,
    get_terminal_status,
    lookup_payment_status,
)


def test_customer_profile_reads_seeded_demo_customer(db):
    result = get_customer_profile(db, "cliente1988")
    assert result["ok"] is True
    assert result["data"]["merchant_name"] == "Comércio Demo 1988"
    assert result["data_environment"] == "synthetic_demo"


def test_unknown_customer_is_not_fabricated(db):
    result = get_customer_profile(db, "someone-else")
    assert result["ok"] is False
    assert result["error"] == "demo_customer_not_found"


def test_terminal_status_reads_actual_sqlite_row(db):
    result = get_terminal_status(db, "cliente1988")
    assert result["ok"] is True
    assert result["data"]["model"] == "Get Smart"
    assert result["data"]["status"] == "offline"
    assert result["data"]["error_code"] == "NET-001"


def test_payment_lookup_returns_yesterdays_approved_sales(db):
    result = lookup_payment_status(db, "cliente1988", "yesterday")
    assert result["ok"] is True
    assert result["approved_count"] == 2
    assert result["net_total_brl"] == 361.55
    assert result["transaction_date"] == (date.today() - timedelta(days=1)).isoformat()
    assert all(t["transaction_status"] == "approved" for t in result["transactions"])
    assert result["data_environment"] == "synthetic_demo"


def test_declined_transactions_are_retrieved_from_database(db):
    result = find_declined_transactions(db, "cliente1988", "yesterday")
    assert result["ok"] is True
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["error_code"] == "05"


def test_payment_lookup_does_not_leak_other_user_records(db):
    result = lookup_payment_status(db, "demo-user-001", "yesterday")
    assert result["approved_count"] == 1
    assert all(t["transaction_id"] != "TX-DEMO-1001" for t in result["transactions"])
