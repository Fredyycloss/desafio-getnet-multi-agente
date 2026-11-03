from __future__ import annotations

import pytest
from tests.conftest import AutoAuthClient as TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint_reports_offline_fallback_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["mode"] == "deterministic_fallback"
    assert response.headers.get("x-request-id")


def test_agents_endpoint_documents_real_specialists(client):
    result = client.get("/api/agents").json()
    names = [x["name"] for x in result["specialists"]]
    assert result["entry_agent"] == "ContextIntelligence"
    assert result["message_flow"][0] == "ContextIntelligence"
    assert "KnowledgeAgent" in names
    assert "CustomerSupportAgent" in names
    assert "CriticAgent" in names


def test_chat_uses_real_rag_for_get_lite(client):
    response = client.post("/api/chat", json={"message": "A Get Lite tem aluguel mensal?", "user_id": "cliente1988"})
    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "pt"
    assert data["trace"][0] == "context_intelligence"
    assert data["context_assessment"]["recommended_action"] == "route_to_agent"
    assert data["retrieved_chunks"] > 0
    assert any("get-lite" in source["url"] for source in data["sources"])
    assert "sem aluguel" in data["answer"].lower()


def test_chat_uses_sqlite_customer_tools_for_yesterday_sales(client):
    response = client.post("/api/chat", json={"message": "When will the money from yesterday's sales be deposited?", "user_id": "cliente1988"})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "customer_support"
    assert "synthetic" in data["answer"].lower()
    assert "TX-DEMO-1001" in data["answer"]


def test_chat_routes_weather_to_public_provider_tool(client, monkeypatch):
    from app.agents.web_research_agent import WebResearchAgent
    monkeypatch.setattr(WebResearchAgent, "weather", lambda self, question, language: {"answer": "Forecast mock 25°C", "confidence": .9, "sources": [{"title": "Open-Meteo", "url": "https://open-meteo.com/"}], "trace": ["web_research_agent", "open_meteo_forecast"], "tool_result": {"tool": "open_meteo_weather"}})
    response = client.post("/api/chat", json={"message": "What's the weather forecast in Porto Alegre tomorrow?", "user_id": "cliente1988"})
    assert response.status_code == 200
    assert response.json()["intent"] == "general_information"
    assert response.json()["sources"][0]["url"] == "https://open-meteo.com/"


def test_chat_escalates_critical_physical_hazard_and_returns_protocol(client):
    response = client.post("/api/chat", json={"message": "Minha maquininha explodiu e está soltando fumaça", "user_id": "cliente1988"})
    assert response.status_code == 200
    data = response.json()
    assert data["handoff"] is True
    assert data["handoff_severity"] == "critical"
    assert data["handoff_protocol"].startswith("GET-")
    assert data["real_agent_connected"] is False
    ticket = client.get(f"/api/handoffs/{data['handoff_protocol']}", params={"user_id": "cliente1988"})
    assert ticket.status_code == 200
    assert ticket.json()["status"] == "queued"


def test_explicit_human_request_creates_persistent_ticket(client):
    # This is the same request body the visible frontend button sends.
    response = client.post("/api/chat", json={"message": "Quero falar com atendimento humano.", "user_id": "cliente1988"})
    assert response.status_code == 200
    assert response.json()["handoff"] is True
    assert "não há atendente real conectado" in response.json()["answer"].lower()
    assert response.json()["handoff_status"] == "queued"
    assert "aguardando atendimento" in response.json()["answer"].lower()


def test_every_chat_turn_passes_context_interpretation_before_risk_and_handoff(client, monkeypatch):
    from app.main import state
    from app.agents.context_intelligence import ContextIntelligence

    service = state["service"]
    events = []

    def context_first(message, history, language, trace_id, *, selected_option=None):
        events.append("context_intelligence")
        return ContextIntelligence(None)._deterministic_assessment(), "test_context_interpreter"

    def risk_after_context(message, history, language):
        events.append("risk_assessment")
        return {"requires_handoff": False, "severity": "normal", "trace": ["risk_assessment_agent"]}

    monkeypatch.setattr(service.context_intelligence, "assess", context_first)
    monkeypatch.setattr(service.risk, "assess", risk_after_context)
    response = client.post("/api/chat", json={"message": "Quero falar com uma pessoa.", "user_id": "cliente1988"})

    assert response.status_code == 200
    assert events[:2] == ["context_intelligence", "risk_assessment"]
    assert response.json()["trace"][0] == "context_intelligence"
    assert response.json()["handoff"] is True


def test_human_handoff_persists_prior_context_and_followup_in_session(client):
    session_id = "handoff-context-session"
    first = client.post("/api/chat", json={
        "message": "Minha maquininha não conecta desde ontem.", "user_id": "cliente1988", "session_id": session_id,
    })
    handoff = client.post("/api/chat", json={
        "message": "Quero falar com atendimento humano.", "user_id": "cliente1988", "session_id": session_id,
    })
    assert first.status_code == handoff.status_code == 200
    data = handoff.json()
    ticket = client.get(f"/api/handoffs/{data['handoff_protocol']}", params={"user_id": "cliente1988"}).json()
    assert any(item["content"] == "Minha maquininha não conecta desde ontem." for item in ticket["messages"])
    assert any(item["content"] == "Quero falar com atendimento humano." for item in ticket["messages"])

    updated = client.post(f"/api/handoffs/{data['handoff_protocol']}/messages", json={
        "message": "Acontece quando uso o Wi-Fi.", "user_id": "cliente1988",
    })
    conversation = client.get(f"/api/sessions/{session_id}/messages", params={"user_id": "cliente1988"}).json()["messages"]
    assert updated.status_code == 200
    assert conversation[-2]["content"] == "Acontece quando uso o Wi-Fi."
    assert "adicionada à solicitação" in conversation[-1]["content"]


def test_handoff_queue_failure_returns_clear_unconfirmed_status(client, monkeypatch):
    from app.main import state
    import sqlite3

    def unavailable(**kwargs):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(state["service"].handoff, "create_ticket", unavailable)
    response = client.post("/api/chat", json={"message": "Quero falar com atendente.", "user_id": "cliente1988"})

    assert response.status_code == 503
    assert "could not be confirmed" in response.json()["detail"]


def test_same_session_loads_previous_turns(client):
    first = client.post("/api/chat", json={"message": "My card machine will not connect", "user_id": "cliente1988", "session_id": "session-followup"})
    second = client.post("/api/chat", json={"message": "And if it still fails?", "user_id": "cliente1988", "session_id": "session-followup"})
    assert first.status_code == second.status_code == 200
    assert second.json()["session_id"] == "session-followup"
    history = client.get("/api/sessions/session-followup/messages", params={"user_id": "cliente1988"}).json()["messages"]
    assert len(history) == 4
    assert history[-2]["content"] == "And if it still fails?"


def test_api_blocks_disclosed_password_but_allows_reset_question(client):
    blocked = client.post("/api/chat", json={"message": "My password is Secret123", "user_id": "cliente1988", "session_id": "secret-disclosure-session"})
    allowed = client.post("/api/chat", json={"message": "How do I reset my password?", "user_id": "cliente1988"})
    assert "do not share passwords" in blocked.json()["answer"].lower()
    assert allowed.status_code == 200
    history = client.get("/api/sessions/secret-disclosure-session/messages", params={"user_id": "cliente1988"}).json()["messages"]
    assert "Secret123" not in history[0]["content"]
    assert "bloqueada" in history[0]["content"]


def test_invalid_blank_request_is_rejected(client):
    response = client.post("/api/chat", json={"message": "   ", "user_id": "cliente1988"})
    assert response.status_code == 422


def test_metrics_endpoint_exposes_counts_without_message_content(client):
    client.post("/api/chat", json={"message": "What is Get Lite?", "user_id": "cliente1988"})
    metrics = client.get("/api/metrics").json()
    assert metrics["chats"] == 1
    assert metrics["requests"] >= 1
    assert "message" not in metrics


def test_session_history_is_scoped_to_its_owner(client):
    created = client.post("/api/chat", json={"message": "What is Get Lite?", "user_id": "cliente1988", "session_id": "private-session"})
    assert created.status_code == 200
    allowed = client.get("/api/sessions/private-session/messages", params={"user_id": "cliente1988"})
    denied = client.get("/api/sessions/private-session/messages", params={"user_id": "demo-user-001"})
    assert allowed.status_code == 200
    assert denied.status_code == 404


def test_chat_cannot_reuse_another_users_session(client):
    client.post("/api/chat", json={"message": "What is Get Lite?", "user_id": "cliente1988", "session_id": "owned-session"})
    response = client.post("/api/chat", json={"message": "Show me history", "user_id": "demo-user-001", "session_id": "owned-session"})
    assert response.status_code == 404


def test_operator_api_requires_configuration_and_key(client, monkeypatch):
    monkeypatch.delenv("OPERATOR_API_KEY", raising=False)
    disabled = client.get("/api/operator/queue", headers={"X-Operator-ID": "operator-1"})
    assert disabled.status_code == 503
    monkeypatch.setenv("OPERATOR_API_KEY", "test-operator-key")
    unauthorized = client.get("/api/operator/queue", headers={"X-Operator-ID": "operator-1", "X-Operator-Key": "wrong"})
    authorized = client.get("/api/operator/queue", headers={"X-Operator-ID": "operator-1", "X-Operator-Key": "test-operator-key"})
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_operator_can_claim_reply_and_resolve_simulated_handoff(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEY", "test-operator-key")
    handoff = client.post("/api/chat", json={"message": "I want to speak to a human agent", "user_id": "cliente1988"}).json()
    protocol = handoff["handoff_protocol"]
    headers = {"X-Operator-ID": "operator-ana", "X-Operator-Key": "test-operator-key"}
    claimed = client.post(f"/api/operator/tickets/{protocol}/claim", headers=headers)
    assert claimed.status_code == 200
    assert claimed.json()["ticket"]["status"] == "assigned"
    reply = client.post(f"/api/operator/tickets/{protocol}/messages", headers=headers, json={"message": "Recebi sua solicitação e estou analisando."})
    assert reply.status_code == 200
    assert reply.json()["ticket"]["messages"][-1]["role"] == "operator"
    resolved = client.post(f"/api/operator/tickets/{protocol}/resolve", headers=headers, json={"resolution": "Orientação demonstrativa registrada."})
    assert resolved.status_code == 200
    assert resolved.json()["ticket"]["status"] == "resolved"
    assert resolved.json()["ticket"]["real_agent_connected"] is False


def test_handoff_ticket_is_private_to_its_demo_user(client):
    handoff = client.post("/api/chat", json={"message": "I want to speak to a human agent", "user_id": "cliente1988"}).json()
    protocol = handoff["handoff_protocol"]
    owner = client.get(f"/api/handoffs/{protocol}", params={"user_id": "cliente1988"})
    other_user = client.get(f"/api/handoffs/{protocol}", params={"user_id": "demo-user-001"})
    assert owner.status_code == 200
    assert other_user.status_code == 404


def test_customer_cannot_append_to_another_users_ticket(client):
    handoff = client.post("/api/chat", json={"message": "I want to speak to a human agent", "user_id": "cliente1988"}).json()
    protocol = handoff["handoff_protocol"]
    response = client.post(f"/api/handoffs/{protocol}/messages", json={"message": "Attempted access", "user_id": "demo-user-001"})
    assert response.status_code == 404


def test_global_handoff_queue_requires_operator_credentials(client, monkeypatch):
    response = client.get("/api/handoffs")
    assert response.status_code == 503
    monkeypatch.setenv("OPERATOR_API_KEY", "test-operator-key")
    denied = client.get("/api/handoffs", headers={"X-Operator-ID": "operator-1", "X-Operator-Key": "bad"})
    allowed = client.get("/api/handoffs", headers={"X-Operator-ID": "operator-1", "X-Operator-Key": "test-operator-key"})
    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_chat_response_and_metrics_expose_model_usage(client):
    response = client.post("/api/chat", json={"message": "What is Get Lite?", "user_id": "cliente1988"})
    usage = response.json()["model_usage"]
    assert usage["llm_calls"] == 0  # LLM disabled in this suite
    assert set(usage) >= {"llm_calls", "prompt_tokens", "output_tokens", "calls"}
    metrics = client.get("/api/metrics").json()
    assert metrics["model"]["calls"] == 0
    assert "by_purpose" in metrics["model"]
