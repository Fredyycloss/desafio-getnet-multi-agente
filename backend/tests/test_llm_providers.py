"""Contract tests for the provider layer. No API key, no internet: the SDK client is faked."""
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infra.llm import LLMBudgetExceeded, LLMTimeout, LLMUnavailable, create_llm, resolve_provider_name
from app.infra.llm.anthropic_provider import AnthropicProvider, strict_schema, to_anthropic_messages
from app.infra.llm.ollama import OllamaProvider

SECRET = "fake-anthropic-key-TEST-SENTINEL-0123456789abcdef"


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in vars(self).items() if v is not None}


def text(value):
    return Block(type="text", text=value)


def tool_use(id_, name, args):
    return Block(type="tool_use", id=id_, name=name, input=args)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **params):
        self.calls.append(params)
        item = self.responses.pop(0) if self.responses else _response([text("ok")])
        if isinstance(item, Exception):
            raise item
        return item


def _response(content, *, stop="end_turn", input_tokens=1000, output_tokens=200):
    return SimpleNamespace(content=content, stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


class FakeClient:
    def __init__(self, responses=()):
        self.messages = FakeMessages(responses)


class FakeEmbedder:
    embedding_model = "nomic-embed-text"

    def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]

    def health(self):
        return {"available": True, "embedding_model_loaded": True}


TOOLS = [{"type": "function", "function": {"name": "knowledge_specialist", "description": "RAG",
                                           "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                                                          "required": ["query"]}}}]


# -- Anthropic adapter -------------------------------------------------------------

def test_anthropic_normalises_text_tool_calls_usage_and_cost():
    client = FakeClient([_response([text("Vou consultar."), tool_use("toolu_1", "knowledge_specialist", {"query": "Pix"})])])
    llm = AnthropicProvider(client=client, embedder=FakeEmbedder())
    result = llm.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "Taxa do Pix?"}],
                      TOOLS, max_tokens=80, temperature=0.0, purpose="supervisor_plan")

    assert result["provider"] == "anthropic" and result["model"] == "claude-haiku-5-5"
    assert result["content"] == "Vou consultar."
    assert result["tool_calls"] == [{"id": "toolu_1", "function": {"name": "knowledge_specialist", "arguments": {"query": "Pix"}}}]
    assert result["message"]["tool_calls"] == result["tool_calls"]
    # $0.10 / $0.50 per MTok -> 1000 in + 200 out = $0.0002
    assert result["usage"] == {"prompt_tokens": 1000, "output_tokens": 200, "latency_ms": result["usage"]["latency_ms"],
                               "cost_usd": 0.0002}
    sent = client.messages.calls[0]
    assert sent["system"] == "sys"
    assert sent["tools"][0] == {"name": "knowledge_specialist", "description": "RAG",
                                "input_schema": TOOLS[0]["function"]["parameters"]}
    assert "temperature" not in sent  # current models reject non-default sampling
    assert sent["max_tokens"] >= 1024 and sent["thinking"] == {"type": "disabled"}
    assert sent["timeout"] > 0


def test_anthropic_tool_round_trip_keeps_ids_and_closes_unexecuted_calls():
    client = FakeClient([_response([tool_use("toolu_a", "knowledge_specialist", {"query": "x"}),
                                    tool_use("toolu_b", "knowledge_specialist", {"query": "y"})]),
                         _response([text("FINAL")])])
    llm = AnthropicProvider(client=client)
    messages = [{"role": "user", "content": "hint"}, {"role": "user", "content": "Request"}]
    first = llm.chat(messages, TOOLS)
    messages.append(first["message"])
    messages.append({"role": "tool", "tool_name": "knowledge_specialist", "content": "observation A"})
    llm.chat(messages, TOOLS)

    wire = client.messages.calls[1]["messages"]
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]  # consecutive user turns merged
    results = wire[2]["content"]
    assert results[0] == {"type": "tool_result", "tool_use_id": "toolu_a", "content": "observation A"}
    assert results[1]["tool_use_id"] == "toolu_b" and results[1]["is_error"] is True


def test_anthropic_json_schema_uses_structured_output_subset():
    from app.agents.context_intelligence import context_output_schema
    client = FakeClient([_response([text(json.dumps({"approved": True}))])])
    AnthropicProvider(client=client).chat([{"role": "user", "content": "x"}], json_schema=context_output_schema(),
                                          purpose="context_intelligence")
    fmt = client.messages.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    dumped = json.dumps(fmt["schema"])
    assert fmt["schema"]["additionalProperties"] is False
    assert "maxLength" not in dumped and "maximum" not in dumped
    assert strict_schema({"type": "object", "properties": {"a": {"type": "string", "maxLength": 3}}}) == {
        "type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False, "required": ["a"]}


def test_anthropic_refusal_timeout_and_errors_map_to_provider_neutral_exceptions():
    import anthropic
    import httpx
    request = httpx.Request("POST", "https://api.anthropic.invalid/v1/messages")
    client = FakeClient([_response([], stop="refusal"), anthropic.APITimeoutError(request=request),
                         anthropic.APIConnectionError(request=request)])
    llm = AnthropicProvider(client=client)
    with pytest.raises(LLMUnavailable):
        llm.chat([{"role": "user", "content": "x"}])
    with pytest.raises(LLMTimeout):
        llm.chat([{"role": "user", "content": "x"}])
    with pytest.raises(LLMUnavailable):
        llm.chat([{"role": "user", "content": "x"}])


def test_anthropic_call_is_not_started_when_request_budget_is_exhausted(monkeypatch):
    from app.observability import current_timeline, finish_timeline, start_timeline
    client = FakeClient()
    token = start_timeline("budget")
    try:
        current_timeline().llm_deadline = 0  # already in the past
        with pytest.raises(LLMBudgetExceeded):
            AnthropicProvider(client=client).chat([{"role": "user", "content": "x"}])
    finally:
        finish_timeline(token)
    assert client.messages.calls == []


def test_anthropic_embeddings_stay_local():
    llm = AnthropicProvider(client=FakeClient(), embedder=FakeEmbedder())
    assert llm.embed(["a", "b"]) == [[0.1, 0.2], [0.1, 0.2]]
    assert llm.embedding_model == "nomic-embed-text"
    with pytest.raises(LLMUnavailable):
        AnthropicProvider(client=FakeClient()).embed(["a"])


def test_messages_conversion_never_starts_with_assistant():
    system, wire = to_anthropic_messages([{"role": "system", "content": "s"}, {"role": "assistant", "content": "hi"}])
    assert system == "s" and wire[0]["role"] == "user"


# -- Provider selection --------------------------------------------------------------

def test_auto_selects_anthropic_only_with_the_getnet_key(monkeypatch):
    monkeypatch.delenv("GETNET_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)  # must be ignored
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    assert resolve_provider_name() is None
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    assert resolve_provider_name() == "ollama"
    monkeypatch.setenv("GETNET_ANTHROPIC_API_KEY", SECRET)
    assert resolve_provider_name() == "anthropic"
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert resolve_provider_name() == "ollama"
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert resolve_provider_name() is None


def test_explicit_anthropic_without_key_has_no_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("GETNET_ANTHROPIC_API_KEY", raising=False)
    assert create_llm() is None


def test_budget_profiles_cloud_30s_local_150s(monkeypatch):
    monkeypatch.delenv("CLOUD_LLM_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BUDGET_SECONDS", raising=False)
    assert AnthropicProvider(client=FakeClient()).default_budget_seconds == 30
    assert OllamaProvider().default_budget_seconds == 150


# -- Secret handling --------------------------------------------------------------

def test_api_key_never_appears_in_logs_responses_or_metrics(monkeypatch, tmp_path, caplog):
    import anthropic
    from fastapi.testclient import TestClient
    from app.main import app

    seen = {}

    class RecordingAnthropic:
        def __init__(self, *, api_key, timeout, max_retries):
            seen["api_key"] = api_key
            self.messages = FakeMessages([])

    monkeypatch.setattr(anthropic, "Anthropic", RecordingAnthropic)
    monkeypatch.setattr("app.observability._default_budget_seconds", 90.0)  # restored after the test
    monkeypatch.setenv("GETNET_ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-from-WRONG-VARIABLE")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "secret.sqlite3"))
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        login = client.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"})
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        chat = client.post("/api/chat", json={"message": "Qual a taxa do Pix?", "user_id": "cliente1988"}, headers=auth)
        assert chat.status_code == 200
        bodies = [client.get("/api/health").text, login.text, chat.text,
                  client.get("/api/metrics").text]
        health = client.get("/api/health").json()
    assert seen["api_key"] == SECRET  # used, from GETNET_ANTHROPIC_API_KEY only
    assert health["llm_provider"]["provider"] == "anthropic"
    everything = "\n".join(bodies) + "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET not in everything
    assert "sk-ant" not in everything
    assert SECRET not in repr(AnthropicProvider(client=FakeClient()))
    db_bytes = (tmp_path / "secret.sqlite3").read_bytes()
    assert SECRET.encode() not in db_bytes


# -- Architecture guard ------------------------------------------------------------

def test_no_agent_imports_a_provider_client_directly():
    root = Path(__file__).parents[1] / "app"
    offenders = []
    for path in [*root.glob("agents/*.py"), root / "service.py"]:
        source = path.read_text(encoding="utf-8")
        if re.search(r"ollama_client|infra\.llm\.(ollama|anthropic)|^\s*(import|from)\s+anthropic|/api/chat|11434",
                     source, re.M):
            offenders.append(path.name)
    assert offenders == []
