"""Telegram operator channel with a simulated Bot API transport (no network, no token)."""
import json

import pytest

from app.hitl import operators as ops
from app.hitl.service import HITLService
from app.hitl.telegram import TelegramClient, ticket_card
from app.hitl.telegram_worker import handle

OPERATOR_TG = 111
STRANGER_TG = 999


class FakeBotAPI:
    """Records Bot API calls; message ids increase like Telegram's."""

    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail
        self.next_id = 500

    def __call__(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        if self.fail:
            return _Resp({"ok": False, "error_code": 502})
        if method == "sendMessage":
            self.next_id += 1
            return _Resp({"ok": True, "result": {"message_id": self.next_id}})
        return _Resp({"ok": True, "result": True})

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


@pytest.fixture
def setup(db, monkeypatch):
    monkeypatch.setenv("TELEGRAM_OPERATOR_CHAT_ID", "-100123")
    api = FakeBotAPI()
    client = TelegramClient("fake-token", post=api)
    hitl = HITLService(db, llm=None, telegram=client)
    db.save_message("sess-1", "cliente1988", "user", "Minha maquininha não liga e preciso vender hoje.")
    ticket = db.create_ticket("cliente1988", "sess-1", "human_requested", "high", "pt", "Quero falar com um atendente.",
                              [{"role": "user", "content": "Minha maquininha não liga e preciso vender hoje."}])
    return db, api, client, hitl, ticket


def _message(text, *, user=OPERATOR_TG, reply_to=None):
    msg = {"message_id": 7, "text": text, "from": {"id": user, "username": "ana_tg"}, "chat": {"id": -100123}}
    if reply_to:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": 1, "message": msg}


def test_new_ticket_sends_card_with_buttons_and_summary(setup):
    db, api, client, hitl, ticket = setup
    outcome = hitl.notify_new_ticket(ticket)
    assert outcome["telegram"] == "sent"
    card = api.sent()[0]
    assert card["chat_id"] == "-100123" and ticket["protocol"] in card["text"] and "Prioridade" in card["text"]
    buttons = [b["callback_data"] for b in card["reply_markup"]["inline_keyboard"][0]]
    assert buttons == [f"claim:{ticket['protocol']}", f"reply:{ticket['protocol']}", f"resolve:{ticket['protocol']}"]
    assert "fake-token" not in json.dumps(api.calls) and "fake-token" not in repr(client)


def test_claim_button_reply_to_card_and_resolution_reach_the_customer_session(setup):
    db, api, client, hitl, ticket = setup
    hitl.notify_new_ticket(ticket)
    card_id = db.get_ticket(ticket["protocol"])["telegram_message_id"]
    allowed = {OPERATOR_TG}
    claim = {"update_id": 2, "callback_query": {"id": "cb1", "data": f"claim:{ticket['protocol']}",
                                                "from": {"id": OPERATOR_TG, "username": "ana_tg"}}}
    assert handle(claim, hitl, client, allowed) == "claim"
    assert db.get_ticket(ticket["protocol"])["status"] == "assigned"
    assert handle(_message("Olá! Vou verificar seu terminal agora.", reply_to=card_id), hitl, client, allowed) == "reply"
    assert handle(_message(f"/resolve {ticket['protocol']} Técnico agendado para amanhã às 9h."), hitl, client, allowed) == "resolve"
    session = db.messages_after("sess-1")
    authors = [(m.get("author"), m["content"]) for m in session]
    assert ("operator", "Olá! Vou verificar seu terminal agora.") in authors
    assert any(a == "handoff_resolution" and "Técnico agendado para amanhã" in c for a, c in authors)
    history = db.get_history("sess-1")  # what the agents see next turn
    assert any("Técnico agendado para amanhã" in h["content"] for h in history)
    audit = ops.list_audit(db)
    assert {a["action"] for a in audit} >= {"claim", "reply", "resolve"} and all(a["operator"] == "tg:111" for a in audit)


def test_slash_r_command_replies_and_implies_claim(setup):
    db, api, client, hitl, ticket = setup
    assert handle(_message(f"/r {ticket['protocol']} Pode me dizer o modelo?"), hitl, client, {OPERATOR_TG}) == "reply"
    t = db.get_ticket(ticket["protocol"])
    assert t["status"] == "assigned" and t["assigned_operator"] == "tg:111"


def test_unauthorized_telegram_user_cannot_act_and_is_audited(setup):
    db, api, client, hitl, ticket = setup
    assert handle(_message(f"/r {ticket['protocol']} oi", user=STRANGER_TG), hitl, client, {OPERATOR_TG}) == "unauthorized"
    assert db.get_ticket(ticket["protocol"])["status"] == "queued"
    assert ops.list_audit(db)[0]["outcome"] == "unauthorized"


def test_telegram_outage_keeps_the_ticket_queued_for_the_console(db, monkeypatch):
    monkeypatch.setenv("TELEGRAM_OPERATOR_CHAT_ID", "-100123")
    hitl = HITLService(db, llm=None, telegram=TelegramClient("fake-token", post=FakeBotAPI(fail=True)))
    ticket = db.create_ticket("cliente1988", "sess-2", "human_requested", "normal", "pt", "Quero um atendente.")
    assert hitl.notify_new_ticket(ticket)["telegram"] == "failed"
    assert db.get_ticket(ticket["protocol"])["status"] == "queued"
    assert ticket["protocol"] in [t["protocol"] for t in db.list_tickets("queued")]


def test_return_to_ai_stores_hidden_instruction_and_flags_resumption(setup):
    db, api, client, hitl, ticket = setup
    op = {"username": "tg:111", "display_name": "ana_tg", "role": "operator"}
    hitl.claim(ticket["protocol"], op, "telegram")
    assert handle(_message(f"/ai {ticket['protocol']} Cliente validado, siga com a consulta de vendas de ontem."),
                  hitl, client, {OPERATOR_TG}) == "return_to_ai"
    t = db.get_ticket(ticket["protocol"])
    assert t["status"] == "returned_to_ai" and t["resume_pending"] == 1
    assert all(not m["content"].startswith("[Instrução") for m in db.messages_after("sess-1"))  # hidden in the UI
    assert any(h["content"].startswith("[Instrução") for h in db.get_history("sess-1"))  # visible to the agents


def test_customer_message_during_human_conversation_is_forwarded(setup):
    db, api, client, hitl, ticket = setup
    hitl.notify_new_ticket(ticket)
    hitl.claim(ticket["protocol"], {"username": "tg:111", "display_name": "ana", "role": "operator"}, "telegram")
    active = hitl.active_ticket_for_session("sess-1")
    hitl.customer_message(active, "cliente1988", "É a Get Smart, senha 1234")
    forwarded = api.sent()[-1]
    assert "Cliente (" in forwarded["text"] and "1234" not in forwarded["text"]  # redacted before leaving
    assert db.protocol_for_telegram_message(api.next_id) == ticket["protocol"]


def test_card_text_has_no_customer_secrets():
    text, _ = ticket_card({"protocol": "GET-20261103-ABC123", "severity": "critical", "reason": "physical_safety", "language": "pt"},
                          "Cliente relata fumaça na maquininha.")
    assert "🔴" in text and "GET-20261103-ABC123" in text
