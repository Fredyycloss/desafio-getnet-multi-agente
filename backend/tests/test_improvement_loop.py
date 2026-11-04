"""Improvement loop with human review: feedback, validated answers, knowledge gaps (V6 block 6)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.infra.llm import LLMUnavailable
from app.infra.llm.base import LLMProvider, normalised_response
from tests.test_agents_and_orchestration import context_assessment


class LoopModel(LLMProvider):
    provider, model, embedding_model = "scripted", "loop", ""

    def _r(self, content="", calls=None):
        return normalised_response(content=content, tool_calls=calls or [], provider="scripted", model=self.model,
                                   prompt_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0)

    def chat(self, messages, tools=None, *, purpose="chat", **kwargs):
        if purpose == "context_intelligence":
            text = json.loads(messages[-1]["content"])["current_message"].casefold()
            if "esquisit" in text or "tela do terminal" in text:
                return self._r(json.dumps(context_assessment(intent="unclear", ambiguity_level="high", needs_clarification=True,
                                                             recommended_action="clarify", recommended_destination="clarification",
                                                             confidence=0.3)))
            agent = "payments_specialist" if "vendas" in text else "knowledge_specialist"
            return self._r(json.dumps(context_assessment(recommended_agents=[agent], recommended_destination=agent, confidence=0.95)))
        if purpose == "knowledge:tool_selection":
            return self._r(calls=[{"id": "k", "function": {"name": "search_getnet_knowledge", "arguments": {"query": "Get Lite aluguel"}}}])
        if purpose == "payments_agent:tool_selection":
            return self._r(calls=[{"id": "p", "function": {"name": "lookup_payment_status", "arguments": {"period": "yesterday"}}}])
        if purpose == "knowledge":
            return self._r("A Get Lite não tem aluguel mensal [1].")
        if purpose == "payments_agent:answer":
            return self._r("Registros demonstrativos sintéticos: venda TX-DEMO-1001.")
        if purpose == "critic":
            return self._r(json.dumps({"approved": True, "issues": []}))
        return self._r("ok")

    def embed(self, texts):
        raise LLMUnavailable("none")

    def health(self):
        return {"available": True, "chat_model_loaded": True, "embedding_model_loaded": False}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "loop.sqlite3"))
    import app.main as main
    monkeypatch.setattr(main, "create_llm", lambda: LoopModel())
    return TestClient(main.app)


def _token(client, user="cliente1988", pin="1988"):
    return {"Authorization": "Bearer " + client.post("/api/auth/demo-login", json={"user_id": user, "pin": pin}).json()["access_token"]}


def _op(client, user, password):
    return {"Authorization": "Bearer " + client.post("/api/operator/login", json={"username": user, "password": password}).json()["access_token"]}


def _ask(client, headers, message, session, user="cliente1988"):
    return client.post("/api/chat", json={"message": message, "user_id": user, "session_id": session}, headers=headers).json()


def test_thumbs_up_validates_a_knowledge_answer_reused_until_the_corpus_changes(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        a = _token(client)
        first = _ask(client, a, "A Get Lite tem aluguel mensal?", "v1")
        assert "tool:knowledge_specialist" in first["trace"]
        r = client.post("/api/feedback", json={"trace_id": first["trace_id"], "rating": "up"}, headers=a).json()
        assert r["validated"] is True
        again = _ask(client, a, "a get lite tem aluguel mensal", "v2")  # same question, other conversation
        observations = json.dumps(again.get("specialist_observations"), ensure_ascii=False)
        assert "validated_answer_hit" in observations and again["answer"] == first["answer"]
        import app.main as main
        main.state["service"].improvement.corpus_version = "2099-01-01:new:curated0"  # corpus refreshed
        later = _ask(client, a, "A Get Lite tem aluguel mensal?", "v3")
        assert "validated_answer_hit" not in json.dumps(later.get("specialist_observations"), ensure_ascii=False)


def test_customer_data_answers_are_never_validated_and_feedback_stores_no_text(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        a = _token(client)
        sales = _ask(client, a, "Quando caem as vendas de ontem?", "p1")
        r = client.post("/api/feedback", json={"trace_id": sales["trace_id"], "rating": "up"}, headers=a).json()
        assert r["validated"] is False
        import app.main as main
        db = main.state["db"]
        columns = {row[1] for row in db.conn.execute("PRAGMA table_info(feedback)").fetchall()}
        assert columns == {"id", "trace_id", "user_id", "rating", "reason", "created_at"}
        assert db.conn.execute("SELECT COUNT(*) FROM validated_answers").fetchone()[0] == 0


def test_feedback_only_on_own_answers(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        a, b = _token(client), _token(client, "demo-user-001", "0001")
        turn = _ask(client, a, "A Get Lite tem aluguel mensal?", "own")
        assert client.post("/api/feedback", json={"trace_id": turn["trace_id"], "rating": "up"}, headers=b).status_code == 404
        assert client.post("/api/feedback", json={"trace_id": turn["trace_id"], "rating": "maybe"}, headers=a).status_code == 422


def test_gaps_are_queued_and_only_an_operator_promotes(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        a = _token(client)
        _ask(client, a, "Minha conta está esquisita desde segunda.", "g1")             # clarification -> gap
        _ask(client, a, "A tela do terminal ficou toda branca depois da atualização.", "g2")  # text from heldout_v2
        down = _ask(client, a, "A Get Lite tem aluguel mensal?", "g3")
        client.post("/api/feedback", json={"trace_id": down["trace_id"], "rating": "down", "reason": "incomplete"}, headers=a)
        assert client.get("/api/operator/knowledge-gaps", headers=a).status_code == 401  # customer token is not an operator
        ana, bruno = _op(client, "ana.operadora", "demo-ana-2026"), _op(client, "bruno.supervisor", "demo-bruno-2026")
        gaps = {g["kind"] + ":" + g["question"][:12]: g for g in client.get("/api/operator/knowledge-gaps", headers=ana).json()["items"]}
        assert {k.split(":")[0] for k in gaps} == {"clarification", "thumbs_down"}
        mine = next(g for k, g in gaps.items() if "esquisita" in g["question"])
        dataset = next(g for g in gaps.values() if "tela do terminal" in g["question"])
        official = "https://site.getnet.com.br/get-ajuda/"
        assert client.post(f"/api/operator/knowledge-gaps/{mine['id']}/decision", headers=ana,
                           json={"action": "promote_kb", "answer": "x" * 30, "source_url": official}).status_code == 403
        assert client.post(f"/api/operator/knowledge-gaps/{mine['id']}/decision", headers=bruno,
                           json={"action": "promote_kb", "answer": "Resposta curada pelo supervisor.", "source_url": "https://example.com"}).status_code == 422
        assert client.post(f"/api/operator/knowledge-gaps/{dataset['id']}/decision", headers=bruno,
                           json={"action": "promote_kb", "answer": "Resposta curada pelo supervisor.", "source_url": official}).status_code == 409
        ok = client.post(f"/api/operator/knowledge-gaps/{mine['id']}/decision", headers=bruno,
                         json={"action": "promote_kb", "answer": "Para revisar a conta, acesse a central de ajuda oficial.", "source_url": official})
        assert ok.status_code == 200 and ok.json()["status"] == "promoted_kb"
        import app.main as main
        curated = main.state["service"].improvement.curated_documents()
        assert len(curated) == 1 and curated[0]["source_type"] == "operator_curated"
        audit = client.get("/api/operator/audit", headers=bruno).json()["items"]
        assert any(e["action"] == "gap_promote_kb" and e["outcome"] == "ok" for e in audit)
