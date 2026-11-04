"""HITL end to end through the HTTP API: handoff, operator console, live messages, resumption."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "hitl.sqlite3"))
    monkeypatch.setenv("AUTH_SECRET", "hitl-test-secret")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPERATOR_API_KEY", raising=False)
    with TestClient(app) as client:
        yield client


def customer(api):
    token = api.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def operator(api, username="ana.operadora", password="demo-ana-2026"):
    response = api.post("/api/operator/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def start_handoff(api, headers, session="hitl-s1"):
    first = api.post("/api/chat", json={"message": "Minha maquininha não liga.", "user_id": "cliente1988", "session_id": session}, headers=headers)
    assert first.status_code == 200
    handoff = api.post("/api/chat", json={"message": "Quero falar com um atendente.", "user_id": "cliente1988", "session_id": session},
                       headers=headers).json()
    assert handoff["handoff"] is True
    return handoff["handoff_protocol"], handoff["last_message_id"]


def test_operator_endpoints_need_individual_login(api):
    assert api.get("/api/operator/queue").status_code == 401
    assert api.post("/api/operator/login", json={"username": "ana.operadora", "password": "errada-123"}).status_code == 401
    token = customer(api)  # a customer token is not an operator token
    assert api.get("/api/operator/queue", headers=token).status_code == 401
    assert api.get("/api/operator/audit", headers=operator(api)).status_code == 403  # operator, not supervisor
    assert api.get("/api/operator/audit", headers=operator(api, "bruno.supervisor", "demo-bruno-2026")).status_code == 200


def test_full_cycle_operator_reply_live_customer_to_ticket_resolution_then_ai(api):
    cust, op = customer(api), operator(api)
    protocol, last_id = start_handoff(api, cust)
    queue = api.get("/api/operator/queue", headers=op).json()
    assert protocol in [t["protocol"] for t in queue["items"]] and queue["real_agent_connected"] is True  # console is live

    assert api.post(f"/api/operator/tickets/{protocol}/claim", headers=op).status_code == 200
    assert api.post(f"/api/operator/tickets/{protocol}/messages", json={"message": "Oi, aqui é a Ana."}, headers=op).status_code == 200

    live = api.get(f"/api/sessions/hitl-s1/messages?after_id={last_id}", headers=cust).json()
    assert any(m.get("author") == "operator" and m["content"] == "Oi, aqui é a Ana." and m.get("operator") for m in live["messages"])
    assert live["ticket"]["status"] == "assigned" and live["ticket"]["status_label"] == "em atendimento"

    # While a human handles the case the customer's message goes to the ticket, not to the agents.
    during = api.post("/api/chat", json={"message": "É a Get Smart do caixa 2.", "user_id": "cliente1988", "session_id": "hitl-s1"},
                      headers=cust).json()
    assert during["orchestration_mode"] == "human_conversation" and during["handoff_status"] == "assigned"
    assert "É a Get Smart do caixa 2." in [m["content"] for m in api.get(f"/api/operator/tickets/{protocol}", headers=op).json()["messages"]]

    assert api.post(f"/api/operator/tickets/{protocol}/resolve", json={"resolution": "Técnico agendado para amanhã às 9h."},
                    headers=op).status_code == 200
    after = api.get(f"/api/sessions/hitl-s1/messages?after_id={last_id}", headers=cust).json()
    assert after["ticket"]["status"] == "resolved"
    assert any("Técnico agendado para amanhã às 9h." in m["content"] and m.get("author") == "handoff_resolution" for m in after["messages"])

    # Back to the AI: the next question is answered by the agents with the resolution in the history.
    next_turn = api.post("/api/chat", json={"message": "Obrigado. Qual a taxa do Pix?", "user_id": "cliente1988", "session_id": "hitl-s1"},
                         headers=cust).json()
    assert next_turn["orchestration_mode"] != "human_conversation"
    history = api.get("/api/sessions/hitl-s1/messages", headers=cust).json()["messages"]
    assert any("Técnico agendado para amanhã" in m["content"] for m in history)


def test_return_to_ai_with_instruction_resumes_the_supervisor(api):
    cust, op = customer(api), operator(api)
    protocol, last_id = start_handoff(api, cust, session="hitl-s2")
    api.post(f"/api/operator/tickets/{protocol}/claim", headers=op)
    response = api.post(f"/api/operator/tickets/{protocol}/return-to-ai",
                        json={"instruction": "Cliente validado; siga com a consulta das vendas de ontem."}, headers=op)
    assert response.status_code == 200 and response.json()["resumed"] is True
    live = api.get(f"/api/sessions/hitl-s2/messages?after_id={last_id}", headers=cust).json()["messages"]
    assert any(m.get("author") == "assistant_resume" for m in live)
    assert all("Instrução do atendente" not in m["content"] for m in live)  # instruction hidden from the customer


def test_other_customer_cannot_poll_a_session(api):
    cust = customer(api)
    start_handoff(api, cust, session="hitl-s3")
    other = api.post("/api/auth/demo-login", json={"user_id": "demo-user-001", "pin": "0001"}).json()["access_token"]
    assert api.get("/api/sessions/hitl-s3/messages?after_id=0", headers={"Authorization": f"Bearer {other}"}).status_code == 404
