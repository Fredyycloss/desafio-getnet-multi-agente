from app.agents.guardrails import inspect_message
from app.infra.database import Database
from app.language import detect_language


def test_password_reset_question_is_not_blocked():
    assert inspect_message("How do I reset my password?", "en")["blocked"] is False


def test_secret_value_is_blocked():
    result = inspect_message("My password is Secret123!", "en")
    assert result["blocked"] is True


def test_full_card_number_is_blocked():
    result = inspect_message("My card is 4111 1111 1111 1111", "en")
    assert result["blocked"] is True


def test_language_follows_short_english_continuation():
    assert detect_language("And if it still fails?", [{"role": "user", "content": "My card machine does not connect"}]) == "en"


def test_language_follows_short_portuguese_continuation():
    assert detect_language("E se continuar?", [{"role": "user", "content": "Minha maquininha não conecta"}]) == "pt"


def test_session_memory_is_persisted_in_sqlite(db):
    db.save_message("session-1", "cliente1988", "user", "My terminal is offline")
    db.save_message("session-1", "cliente1988", "assistant", "I checked the demo terminal status")
    history = db.get_history("session-1")
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "My terminal is offline"


def test_clarification_options_survive_in_conversation_history(db):
    options = [{"id": "human_support", "label": "Falar com atendente humano"}]
    db.save_message(
        "clarification-session",
        "cliente1988",
        "assistant",
        "Escolha um assunto.",
        {"clarification_options": options, "private_unneeded_value": "not returned"},
    )

    history = db.get_history("clarification-session")

    assert history[0]["clarification_options"] == options
    assert "private_unneeded_value" not in history[0]


def test_ticket_content_redacts_email_and_card_number(db):
    ticket = db.create_ticket("cliente1988", "session-2", "human_requested", "normal", "en", "Contact me at user@example.com, card 4111111111111111")
    assert "user@example.com" not in ticket["summary"]
    assert "4111111111111111" not in ticket["summary"]


def test_tool_audit_is_recorded(db):
    db.record_tool("trace-1", "lookup_payment_status", "cliente1988", "ok", 5)
    row = db.conn.execute("SELECT tool_name,status,duration_ms FROM tool_audit WHERE trace_id='trace-1'").fetchone()
    assert tuple(row) == ("lookup_payment_status", "ok", 5)


def test_tool_metrics_are_aggregated_without_message_content(db):
    db.record_tool("trace-1", "lookup_payment_status", "cliente1988", "ok", 7)
    db.record_tool("trace-2", "lookup_payment_status", "cliente1988", "error", 13)
    metrics = db.get_tool_metrics()
    assert metrics["calls"] == 2
    assert metrics["failures"] == 1
    assert metrics["by_tool"][0]["average_duration_ms"] == 10.0


def test_model_usage_is_persisted_without_content(db):
    db.record_model_calls("trace-usage", [
        {"purpose": "context_intelligence", "model": "qwen3:1.7b", "prompt_tokens": 300, "output_tokens": 90,
         "load_ms": None, "prompt_ms": 1000.0, "generation_ms": 2000.0},
        {"purpose": "critic", "model": "qwen3:1.7b", "prompt_tokens": 400, "output_tokens": 20,
         "load_ms": 0.0, "prompt_ms": 900.0, "generation_ms": 300.0},
    ])
    metrics = db.get_model_metrics()
    assert metrics["calls"] == 2
    assert metrics["requests_with_llm"] == 1
    assert metrics["prompt_tokens"] == 700
    assert {item["purpose"] for item in metrics["by_purpose"]} == {"context_intelligence", "critic"}
