"""Long-conversation memory (V7-H): incremental summary + structured facts replace old turns."""
from __future__ import annotations

import json

from app.infra.llm import LLMUnavailable
from app.infra.llm.base import LLMProvider, normalised_response
from tests.conftest import AutoAuthClient as TestClient
from tests.test_agents_and_orchestration import context_assessment


class MemoryModel(LLMProvider):
    """Records what the Context Intelligence receives; summarises by keeping each user message's start."""
    provider, model, embedding_model = "scripted", "memory", ""

    def __init__(self):
        self.ci_histories: list[list[dict]] = []
        self.summary_inputs: list[str] = []

    def _resp(self, content):
        return normalised_response(content=content, tool_calls=[], provider="scripted", model=self.model,
                                   prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)

    def chat(self, messages, tools=None, *, purpose="chat", **kwargs):
        if purpose == "context_intelligence":
            self.ci_histories.append(json.loads(messages[-1]["content"])["recent_history"])
            return self._resp(json.dumps(context_assessment(confidence=0.95)))
        if purpose == "session_summary":
            payload = json.loads(messages[-1]["content"])
            self.summary_inputs.append(messages[-1]["content"])
            parts = [payload["previous_summary"]] + [m["content"][:60] for m in payload["new_messages"] if m["role"] == "user"]
            return self._resp(" | ".join(p for p in parts if p)[:700])
        if purpose == "critic":
            return self._resp(json.dumps({"approved": True, "issues": []}))
        return self._resp("Resposta [1].")

    def embed(self, texts):
        raise LLMUnavailable("none")

    def health(self):
        return {"available": True, "chat_model_loaded": True, "embedding_model_loaded": False}


def _client(monkeypatch, tmp_path, model):
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "memory.sqlite3"))
    import app.main as main
    monkeypatch.setattr(main, "create_llm", lambda: model)
    return TestClient(main.app)


def _say(client, text, session, user="cliente1988"):
    return client.post("/api/chat", json={"message": text, "user_id": user, "session_id": session}).json()


def test_thirty_turns_keep_old_references_and_save_context(monkeypatch, tmp_path):
    model = MemoryModel()
    with _client(monkeypatch, tmp_path, model) as client:
        _say(client, "Meu estabelecimento é a Padaria Aurora e uso a maquininha TERM-1988.", "long")
        _say(client, "Meu e-mail é joao.silva@exemplo.com, caso precise.", "long")
        for i in range(28):
            _say(client, f"Pergunta de acompanhamento número {i} sobre taxas da Get Smart.", "long")
        last = _say(client, "Qual é o nome do meu estabelecimento que eu disse no começo?", "long")
        import app.main as main
        stored = main.state["db"].conn.execute("SELECT summary FROM session_memory WHERE session_id='long'").fetchone()["summary"]
    history = model.ci_histories[-1]
    joined = json.dumps(history, ensure_ascii=False)
    assert history[0]["content"].startswith("[conversation memory]")
    assert "Padaria Aurora" in joined and "TERM-1988" in joined  # turn 1 survives through the summary + facts
    assert all("número 3 " not in m["content"] for m in history[1:])  # old raw turns are not sent any more
    assert len(history) <= 6
    assert last["memory"]["memory_used"] is True and last["memory"]["chars_replaced"] > 3 * last["memory"]["memory_chars"]
    # Redaction: the summary never stores or sends the e-mail address.
    assert "joao.silva@exemplo.com" not in joined
    assert "joao.silva@exemplo.com" not in stored and "[email]" in stored


def test_memory_is_per_session_and_customer(monkeypatch, tmp_path):
    model = MemoryModel()
    with _client(monkeypatch, tmp_path, model) as client:
        _say(client, "Minha loja se chama Mercearia Horizonte.", "s-one")
        for i in range(14):
            _say(client, f"Mensagem {i} desta conversa.", "s-one")
        _say(client, "Outra conversa, mesma pessoa.", "s-two")
        assert "Horizonte" not in json.dumps(model.ci_histories[-1], ensure_ascii=False)
        other = client.post("/api/chat", json={"message": "Oi", "user_id": "demo-user-001", "session_id": "s-one"})
        assert other.status_code == 404


def test_short_conversations_are_untouched(monkeypatch, tmp_path):
    model = MemoryModel()
    with _client(monkeypatch, tmp_path, model) as client:
        for i in range(4):
            r = _say(client, f"Mensagem {i}", "short")
    assert r["memory"] == {"memory_used": False} and not model.summary_inputs


def test_memory_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_MEMORY", "off")
    model = MemoryModel()
    with _client(monkeypatch, tmp_path, model) as client:
        for i in range(16):
            r = _say(client, f"Mensagem {i}", "off")
    assert r["memory"] == {"memory_used": False} and not model.summary_inputs


def test_memory_note_survives_the_history_window_and_reaches_the_answer_writer(db):
    from app.agents.support_agent import CustomerSupportAgent
    from app.infra.llm.base import normalised_response
    from app.memory import window

    note = {"role": "assistant", "content": "[conversation memory] store: Doceria Primavera", "memory": True}
    history = [note] + [{"role": "user", "content": f"m{i}"} for i in range(6)]
    assert window(history, 4)[0] is note and len(window(history, 4)) == 5
    assert window([{"role": "user", "content": "x"}], 4) == [{"role": "user", "content": "x"}]

    class Model:
        model = "scripted"

        def __init__(self):
            self.prompts = {}

        def chat(self, messages, tools=None, *, purpose="chat", **kwargs):
            self.prompts[purpose] = messages
            calls = [{"id": "1", "function": {"name": "get_terminal_status", "arguments": {}}}] if purpose.endswith(":tool_selection") else []
            return normalised_response(content="" if calls else "ok", tool_calls=calls, provider="t", model="t",
                                       prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)

    model = Model()
    CustomerSupportAgent(db, model).run("Qual é o nome da minha loja?", "cliente1988", "pt", history=history)
    assert any("Doceria Primavera" in m["content"] for m in next(v for k, v in model.prompts.items() if k.endswith(":tool_selection")))
    assert "Doceria Primavera" in next(v for k, v in model.prompts.items() if k.endswith(":answer"))[-1]["content"]
