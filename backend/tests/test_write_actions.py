"""Write actions (V7-F): the model proposes, the customer confirms, code executes once, everything is audited."""
from __future__ import annotations

import json

import pytest

from app.infra.llm import LLMUnavailable
from app.infra.llm.base import LLMProvider, normalised_response
from tests.conftest import AutoAuthClient as TestClient
from tests.test_agents_and_orchestration import context_assessment


class ActionModel(LLMProvider):
    """Context -> one specialist (fast path); the specialist proposes the scripted action."""
    provider, model, embedding_model = "scripted", "scripted-actions", ""

    def __init__(self, agent: str, tool: str, args: dict):
        self.agent, self.tool, self.args = agent, tool, args

    def chat(self, messages, tools=None, *, purpose="chat", **kwargs):
        if purpose == "context_intelligence":
            content = json.dumps(context_assessment(intent="action request", recommended_agents=[self.agent],
                                                    recommended_destination=self.agent, confidence=0.95))
            return normalised_response(content=content, tool_calls=[], provider="scripted", model=self.model,
                                       prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)
        if purpose.endswith(":tool_selection"):
            names = {t["function"]["name"] for t in tools or []}
            calls = [{"id": "c1", "function": {"name": self.tool, "arguments": self.args}}] if self.tool in names else []
            return normalised_response(content="", tool_calls=calls, provider="scripted", model=self.model,
                                       prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)
        if purpose == "critic":
            return normalised_response(content=json.dumps({"approved": True, "issues": []}), tool_calls=[], provider="scripted",
                                       model=self.model, prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)
        return normalised_response(content="ok", tool_calls=[], provider="scripted", model=self.model,
                                   prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)

    def embed(self, texts):
        raise LLMUnavailable("no embeddings")

    def health(self):
        return {"available": True, "chat_model_loaded": True, "embedding_model_loaded": False}


def _client(monkeypatch, tmp_path, model):
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "actions.sqlite3"))
    monkeypatch.setenv("ANTHROPIC_STARTUP_CHECK", "false")
    import app.main as main
    monkeypatch.setattr(main, "create_llm", lambda: model)
    return TestClient(main.app)


def _requests(client, user="cliente1988"):
    return client.get("/api/actions", params={"user_id": user}).json()


def _ask(client, message, session, user="cliente1988"):
    return client.post("/api/chat", json={"message": message, "user_id": user, "session_id": session}).json()


VISIT = ("customer_support_specialist", "propose_technical_visit", {"problem": "não liga após queda"})


def test_nothing_executes_without_confirmation_then_yes_executes_once(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, ActionModel(*VISIT)) as client:
        proposed = _ask(client, "Quero abrir um chamado técnico, a máquina não liga.", "s-act-1")
        action = proposed["pending_action"]
        assert action["kind"] == "technical_visit" and action["status"] == "pending"
        assert "TERM-1988" in proposed["answer"] and "Confirma?" in proposed["answer"]
        assert proposed["critic"]["mode"] == "action_confirmation_check" and proposed["critic"]["approved"] is True
        assert all(a["status"] != "executed" for a in _requests(client)["actions"])  # proposal is not execution

        done = _ask(client, "sim", "s-act-1")
        assert done["intent"] == "action_executed" and done["action_protocol"].startswith("ACT-")
        assert done["action_protocol"] in done["answer"] and done["critic"]["approved"] is True

        again = client.post(f"/api/actions/{action['action_id']}/confirm", params={"user_id": "cliente1988"},
                            json={"session_id": "s-act-1", "confirmation_token": action["confirmation_token"]}).json()
        assert again["intent"] == "action_already_executed" and again["action_protocol"] == done["action_protocol"]
        listing = _requests(client)
        assert sum(1 for a in listing["actions"] if a["status"] == "executed") == 1
        events = [e["event"] for e in listing["audit"]]
        assert {"proposed", "executed", "repeat_confirmation_ignored"} <= set(events)


def test_same_request_later_returns_the_existing_protocol(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, ActionModel(*VISIT)) as client:
        _ask(client, "Abra um chamado técnico, por favor.", "s-idem")
        first = _ask(client, "sim", "s-idem")
        repeat = _ask(client, "Abra um chamado técnico, por favor.", "s-idem-2")
        assert "pending_action" not in repeat and first["action_protocol"] in repeat["answer"]


def test_confirmation_from_another_session_or_customer_does_not_count(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, ActionModel(*VISIT)) as client:
        action = _ask(client, "Quero abrir um chamado técnico.", "s-a")["pending_action"]
        # Same customer, other conversation: "sim" there has nothing pending.
        other = _ask(client, "sim", "s-b")
        assert other.get("intent") != "action_executed"
        # The button with the right token but another session is refused and audited.
        r = client.post(f"/api/actions/{action['action_id']}/confirm", params={"user_id": "cliente1988"},
                        json={"session_id": "s-b", "confirmation_token": action["confirmation_token"]})
        assert r.status_code == 404
        # Another customer with the token: refused.
        r = client.post(f"/api/actions/{action['action_id']}/confirm", params={"user_id": "demo-user-001"},
                        json={"session_id": "s-a", "confirmation_token": action["confirmation_token"]})
        assert r.status_code == 404
        # Wrong token in the right session: refused.
        r = client.post(f"/api/actions/{action['action_id']}/confirm", params={"user_id": "cliente1988"},
                        json={"session_id": "s-a", "confirmation_token": "x" * 24})
        assert r.status_code == 404
        listing = _requests(client)
        assert all(a["status"] == "pending" for a in listing["actions"])
        assert {"other_session", "bad_token"} <= {e["detail"] for e in listing["audit"] if e["event"] == "decision_rejected"}


def test_cancel_and_expiry_never_execute(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, ActionModel(*VISIT)) as client:
        _ask(client, "Quero abrir um chamado técnico.", "s-c")
        assert _ask(client, "cancelar", "s-c")["intent"] == "action_cancelled"
    monkeypatch.setenv("ACTION_CONFIRMATION_TTL_SECONDS", "0")
    with _client(monkeypatch, tmp_path, ActionModel(*VISIT)) as client:
        _ask(client, "Quero abrir um chamado técnico.", "s-e")
        late = _ask(client, "sim", "s-e")
        assert late.get("intent") != "action_executed"
        assert not any(a["status"] == "executed" for a in _requests(client)["actions"])


def test_dispute_only_for_own_transactions(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, ActionModel("payments_specialist", "propose_transaction_dispute",
                                                    {"transaction_id": "TX-DEMO-2001", "reason": "not_recognized"})) as client:
        r = _ask(client, "Quero contestar a transação TX-DEMO-2001.", "s-d")  # belongs to demo-user-001
        assert "pending_action" not in r
        assert not _requests(client)["actions"]
    with _client(monkeypatch, tmp_path, ActionModel("payments_specialist", "propose_transaction_dispute",
                                                    {"transaction_id": "TX-DEMO-1003", "reason": "declined_wrongly"})) as client:
        r = _ask(client, "Quero contestar a transação TX-DEMO-1003.", "s-d2")
        assert r["pending_action"]["kind"] == "transaction_dispute" and "TX-DEMO-1003" in r["answer"]
        assert _ask(client, "sim", "s-d2")["intent"] == "action_executed"


def test_terminal_block_needs_the_typed_phrase(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, ActionModel("customer_support_specialist", "propose_terminal_block", {"reason": "roubada"})) as client:
        r = _ask(client, "Roubaram minha maquininha, bloqueie por favor.", "s-blk")
        assert r["pending_action"]["requires_typed_confirmation"] is True
        assert _ask(client, "sim", "s-blk")["intent"] == "action_needs_typed_confirmation"
        done = _ask(client, "BLOQUEAR TERM-1988", "s-blk")
        assert done["intent"] == "action_executed"
        status = client.post("/api/chat", json={"message": "x", "user_id": "cliente1988"})  # any call; DB checked below
        assert status.status_code == 200
        import app.main as main
        row = main.state["db"].conn.execute("SELECT status FROM terminals WHERE terminal_id='TERM-1988'").fetchone()
        assert row["status"] == "blocked_by_customer"


def test_model_has_no_execute_tool_and_token_is_not_stored_in_history(monkeypatch, tmp_path):
    from app.actions.catalog import KINDS
    assert all(k.tool["function"]["name"].startswith("propose_") for k in KINDS.values())
    with _client(monkeypatch, tmp_path, ActionModel(*VISIT)) as client:
        r = _ask(client, "Quero abrir um chamado técnico.", "s-tok")
        token = r["pending_action"]["confirmation_token"]
        history = client.get("/api/sessions/s-tok/messages", params={"user_id": "cliente1988"}).json()
        assert token not in json.dumps(history)
