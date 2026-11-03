from app.infra.ollama_client import OllamaClient


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"models": [{"name": "qwen3:1.7b"}, {"name": "nomic-embed-text:latest"}]}


def test_health_matches_implicit_latest_embedding_tag(monkeypatch):
    monkeypatch.setattr("app.infra.llm.ollama.requests.get", lambda *args, **kwargs: FakeResponse())

    status = OllamaClient().health()

    assert status["chat_model_loaded"] is True
    assert status["embedding_model_loaded"] is True


def test_health_does_not_match_different_explicit_tag(monkeypatch):
    class TaggedResponse(FakeResponse):
        def json(self):
            return {"models": [{"name": "qwen3:1.7b"}, {"name": "nomic-embed-text:custom"}]}

    monkeypatch.setattr("app.infra.llm.ollama.requests.get", lambda *args, **kwargs: TaggedResponse())

    status = OllamaClient().health()

    assert status["chat_model_loaded"] is True
    assert status["embedding_model_loaded"] is False


def test_chat_sends_json_schema_for_constrained_output(monkeypatch):
    captured = {}

    class ChatResponse(FakeResponse):
        def json(self):
            return {"message": {"content": "{}"}}

    def fake_post(url, **kwargs):
        captured.update(url=url, payload=kwargs["json"])
        return ChatResponse()

    monkeypatch.setattr("app.infra.llm.ollama.requests.post", fake_post)
    schema = {"type": "object", "required": ["risk_level"]}

    OllamaClient().chat([], json_schema=schema, think=False)

    assert captured["url"].endswith("/api/chat")
    assert captured["payload"]["format"] == schema
    assert captured["payload"]["think"] is False


def test_chat_timeout_is_bounded_by_request_llm_budget(monkeypatch):
    from app.observability import finish_timeline, start_timeline

    captured = {}

    class ChatResponse(FakeResponse):
        def json(self):
            return {"message": {"content": "ok"}, "prompt_eval_count": 10, "eval_count": 2}

    def fake_post(url, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return ChatResponse()

    monkeypatch.setattr("app.infra.llm.ollama.requests.post", fake_post)
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("REQUEST_LLM_BUDGET_SECONDS", "30")
    token = start_timeline("budget-trace")
    try:
        OllamaClient().chat([], purpose="unit")
    finally:
        finish_timeline(token)

    assert 0 < captured["timeout"] <= 30


def test_chat_refuses_to_start_when_request_budget_is_exhausted(monkeypatch):
    import pytest

    from app.infra.ollama_client import OllamaBudgetExceeded
    from app.observability import current_timeline, finish_timeline, start_timeline

    def fail_post(*args, **kwargs):
        raise AssertionError("no model call may start after the budget is spent")

    monkeypatch.setattr("app.infra.llm.ollama.requests.post", fail_post)
    token = start_timeline("spent-trace")
    current_timeline().llm_deadline = 0.0
    try:
        with pytest.raises(OllamaBudgetExceeded):
            OllamaClient().chat([], purpose="unit")
    finally:
        finish_timeline(token)


def test_read_timeout_is_reported_as_ollama_timeout(monkeypatch):
    import pytest
    import requests

    from app.infra.ollama_client import OllamaTimeout

    def slow_post(*args, **kwargs):
        raise requests.ReadTimeout("slow")

    monkeypatch.setattr("app.infra.llm.ollama.requests.post", slow_post)
    with pytest.raises(OllamaTimeout):
        OllamaClient().chat([], purpose="unit")
