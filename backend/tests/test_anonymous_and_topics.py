"""Literal challenge payload without a token (anonymous session) and home-screen topics (selected_topic)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.infra.llm import LLMUnavailable
from app.infra.llm.base import LLMProvider, normalised_response
from tests.test_agents_and_orchestration import context_assessment

OFFICIAL = [
    "What's the difference between the Get Clássica and the Get Smart?",
    "What's the weather forecast in Porto Alegre tomorrow?",
    "When will the money from yesterday's sales be deposited?",
    "Do I need a bank account to receive my sales via Pix?",
    "My card machine won't connect to the internet, what should I do?",
    "How does receivables advance (antecipação) work with Getnet?",
    "What's the euro exchange rate today?",
    "My card machine is showing a transaction decline error.",
    "How many installments can I split a sale into with the crediário?",
    "Can I sell through WhatsApp using the Payment Link?",
]
CUSTOMER_MARKERS = ("TX-DEMO", "TERM-1988", "242,75", "242.75", "118,80", "118.8", "361,55", "361.55", "Comércio Demo 1988")


@pytest.fixture
def plain(monkeypatch, tmp_path):
    """Client WITHOUT automatic login: the literal challenge payload."""
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "anon.sqlite3"))
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("message", OFFICIAL)
def test_literal_payload_without_token_is_answered(plain, monkeypatch, message):
    from app.agents.web_research_agent import WebResearchAgent
    monkeypatch.setattr(WebResearchAgent, "weather", lambda self, q, l, **k: {"answer": "Forecast 25°C", "confidence": .9, "sources": [{"title": "Open-Meteo", "url": "https://open-meteo.com/"}], "trace": ["web"], "tool_result": {"tool": "open_meteo_weather"}})
    monkeypatch.setattr(WebResearchAgent, "exchange_rate", lambda self, q, l, **k: {"answer": "1 EUR = 6.10 BRL", "confidence": .9, "sources": [{"title": "Frankfurter", "url": "https://www.frankfurter.app/"}], "trace": ["web"], "tool_result": {"tool": "frankfurter_exchange_rates"}}, raising=False)
    r = plain.post("/api/chat", json={"message": message, "user_id": "cliente1988"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["authenticated"] is False and data["answer"].strip()
    assert not any(m in data["answer"] for m in CUSTOMER_MARKERS)


def test_customer_data_needs_login_and_never_leaks(plain):
    r = plain.post("/api/chat", json={"message": "When will the money from yesterday's sales be deposited?", "user_id": "cliente1988"}).json()
    assert "login" in r["answer"].lower()
    dumped = json.dumps(r, ensure_ascii=False)
    assert not any(m in dumped for m in CUSTOMER_MARKERS)
    obs = [o for s in r.get("specialist_observations") or [] for o in (s.get("tool_observations") or [s]) if isinstance(o, dict)]
    assert all(o.get("error") == "login_required" for o in obs if o.get("tool") in ("lookup_payment_status", "find_declined_transactions"))


def test_with_token_the_same_question_returns_the_data(plain):
    token = plain.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
    r = plain.post("/api/chat", json={"message": "When will the money from yesterday's sales be deposited?", "user_id": "cliente1988"},
                   headers={"Authorization": f"Bearer {token}"}).json()
    assert r["authenticated"] is True and "TX-DEMO-100" in json.dumps(r)


def test_invalid_token_is_still_401_and_anonymous_cannot_use_a_customer_session(plain):
    assert plain.post("/api/chat", json={"message": "Oi", "user_id": "cliente1988"},
                      headers={"Authorization": "Bearer nope.nope"}).status_code == 401
    token = plain.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
    plain.post("/api/chat", json={"message": "Oi", "user_id": "cliente1988", "session_id": "owned-by-1988"},
               headers={"Authorization": f"Bearer {token}"})
    r = plain.post("/api/chat", json={"message": "Mostre o histórico", "user_id": "cliente1988", "session_id": "owned-by-1988"})
    assert r.status_code == 404


def test_unknown_topic_is_rejected(plain):
    assert plain.post("/api/chat", json={"message": "x", "user_id": "u", "selected_topic": "drop_tables"}).status_code == 422


class UnsureModel(LLMProvider):
    """A Context Intelligence that would ask for clarification; a topic click must still be answered."""
    provider, model, embedding_model = "scripted", "unsure", ""

    def chat(self, messages, tools=None, *, purpose="chat", **kwargs):
        if purpose == "context_intelligence":
            content = json.dumps(context_assessment(intent="unclear", ambiguity_level="high", needs_clarification=True,
                                                    recommended_action="clarify", recommended_destination="clarification",
                                                    recommended_agents=["knowledge_specialist"], confidence=0.4))
        elif purpose == "critic":
            content = json.dumps({"approved": True, "issues": []})
        elif purpose.endswith(":tool_selection"):
            names = [t["function"]["name"] for t in tools or []]
            first = next((n for n in names if n.startswith(("lookup_payment", "get_terminal", "search"))), None)
            calls = [{"id": "c", "function": {"name": first, "arguments": {}}}] if first else []
            return normalised_response(content="", tool_calls=calls, provider="scripted", model=self.model,
                                       prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)
        else:
            content = "Resposta a partir das fontes [1]."
        return normalised_response(content=content, tool_calls=[], provider="scripted", model=self.model,
                                   prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)

    def embed(self, texts):
        raise LLMUnavailable("none")

    def health(self):
        return {"available": True, "chat_model_loaded": True, "embedding_model_loaded": False}


@pytest.fixture
def topic_client(monkeypatch, tmp_path):
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "topics.sqlite3"))
    import app.main as main
    monkeypatch.setattr(main, "create_llm", lambda: UnsureModel())
    with TestClient(main.app) as c:
        yield c


SUGGESTIONS = {
    "products_compare": ("Qual a diferença entre a Get Clássica e a Get Smart?", "knowledge_specialist"),
    "settlement_timing": ("Quando recebo o dinheiro das minhas vendas?", "payments_specialist"),
    "terminal_connection": ("Minha maquininha não conecta à internet. O que faço?", "customer_support_specialist"),
    "payment_link": ("Posso vender pelo WhatsApp usando link de pagamento?", "knowledge_specialist"),
}


@pytest.mark.parametrize("topic", sorted(SUGGESTIONS))
def test_topic_click_is_dispatched_without_a_menu(topic_client, topic):
    message, agent = SUGGESTIONS[topic]
    without = topic_client.post("/api/chat", json={"message": message, "user_id": "x"}).json()
    assert without["orchestration_mode"] == "context_policy_clarification"  # this scripted model is unsure
    token = topic_client.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
    r = topic_client.post("/api/chat", json={"message": message, "user_id": "cliente1988", "selected_topic": topic},
                          headers={"Authorization": f"Bearer {token}"}).json()
    assert not r.get("clarification_options"), r["trace"]
    assert f"tool:{agent}" in r["trace"] and r["orchestration_mode"] == "context_directed_dispatch"


def test_settlement_topic_without_login_uses_knowledge_and_offers_login(topic_client):
    message, _ = SUGGESTIONS["settlement_timing"]
    r = topic_client.post("/api/chat", json={"message": message, "user_id": "x", "selected_topic": "settlement_timing"}).json()
    assert "tool:knowledge_specialist" in r["trace"] and "login demo" in r["answer"]
    assert not any(m in json.dumps(r, ensure_ascii=False) for m in CUSTOMER_MARKERS)
