"""Invalid, forbidden or out-of-credit cloud key: real SDK, simulated HTTP transport (no network)."""
import json

import anthropic
import pytest

try:  # the SDK 2.x HTTP stack
    import httpx2 as hx
except ImportError:  # pragma: no cover
    import httpx as hx

from app.infra.llm import LLMAuthError
from app.infra.llm.anthropic_provider import AnthropicProvider
from app.infra.llm.fallback import FallbackProvider

FAKE_KEY = "fake-key-for-transport-tests"
_RealAnthropic = anthropic.Anthropic  # captured before any test patches the constructor
ERRORS = {
    "llm_key_rejected": (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}),
    "llm_key_forbidden": (403, {"type": "error", "error": {"type": "permission_error", "message": "Your API key does not have permission"}}),
    "llm_no_credit": (400, {"type": "error", "error": {"type": "invalid_request_error",
                                                       "message": "Your credit balance is too low to access the Anthropic API."}}),
}


def sdk_client(status: int, body: dict) -> anthropic.Anthropic:
    def handler(request):
        return hx.Response(status, json=body, request=request)
    return _RealAnthropic(api_key=FAKE_KEY, max_retries=0,
                               http_client=anthropic.DefaultHttpxClient(transport=hx.MockTransport(handler)))


class LocalModel:
    """Stands in for the offline Ollama fallback."""
    provider, model, embedding_model, default_budget_seconds = "ollama", "qwen3:1.7b", "nomic-embed-text", 150.0

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        return {"content": "ok", "tool_calls": [], "message": {"role": "assistant", "content": "ok", "tool_calls": []},
                "usage": {}, "provider": self.provider, "model": self.model}

    def describe(self):
        return {"provider": self.provider, "model": self.model}

    def health(self):
        return {"available": True, "chat_model_loaded": True}


@pytest.mark.parametrize("reason", sorted(ERRORS))
def test_sdk_error_is_classified_and_reported_without_the_key(reason, caplog):
    llm = AnthropicProvider(client=sdk_client(*ERRORS[reason]))
    with pytest.raises(LLMAuthError) as info:
        llm.chat([{"role": "user", "content": "Qual a taxa do Pix?"}], purpose="context_intelligence")
    assert info.value.reason == reason
    health = llm.health()
    assert health["available"] is False and health["key_state"] == reason
    assert "modo nuvem configurado, mas" in health["message"]
    assert FAKE_KEY not in json.dumps(health) + str(info.value) + caplog.text


@pytest.mark.parametrize("reason", sorted(ERRORS))
def test_startup_check_reports_the_key_state(reason):
    llm = AnthropicProvider(client=sdk_client(*ERRORS[reason]))
    assert llm.check_key() == reason
    assert llm.key_failure_reason == reason


def test_fallback_to_offline_on_key_failure_and_budget_switches(monkeypatch):
    monkeypatch.setattr("app.observability._default_budget_seconds", 30.0)
    local = LocalModel()
    llm = FallbackProvider(AnthropicProvider(client=sdk_client(*ERRORS["llm_no_credit"])), local)
    response = llm.chat([{"role": "user", "content": "x"}], purpose="knowledge")
    assert response["provider"] == "ollama" and local.calls == 1
    assert llm.fallback_active and llm.fallback_reason == "llm_no_credit"
    assert llm.provider == "ollama" and llm.key_failure_reason is None
    from app.observability import llm_budget_seconds
    assert llm_budget_seconds() == 150.0
    llm.chat([{"role": "user", "content": "y"}])
    assert local.calls == 2  # stays on the fallback, no repeated cloud call


def test_api_reports_refused_key_and_degraded_cause(monkeypatch, tmp_path):
    """Whole API with the real SDK over a 401 transport: health explains it, answers are degraded with the cause."""
    from fastapi.testclient import TestClient
    from app.main import app

    status, body = ERRORS["llm_key_rejected"]
    real = anthropic.Anthropic

    def patched(*, api_key, timeout, max_retries):
        return sdk_client(status, body)

    monkeypatch.setattr(anthropic, "Anthropic", patched)
    monkeypatch.setattr("app.observability._default_budget_seconds", 90.0)
    monkeypatch.setenv("GETNET_ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")  # embeddings fail fast -> BM25
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "key.sqlite3"))
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        token = client.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
        chat = client.post("/api/chat", json={"message": "A Get Lite tem aluguel mensal?", "user_id": "cliente1988"},
                           headers={"Authorization": f"Bearer {token}"})
    assert real is not None
    assert health["cloud_status"]["key_state"] == "llm_key_rejected"
    assert "chave foi recusada" in health["cloud_status"]["message"]
    assert chat.status_code == 200
    assert chat.json()["degraded"] is True and chat.json()["degraded_reason"] == "llm_key_rejected"
    assert FAKE_KEY not in json.dumps(health) + chat.text


def test_api_trace_shows_offline_fallback(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.infra.llm import ollama as ollama_module
    from app.main import app

    status, body = ERRORS["llm_key_rejected"]
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: sdk_client(status, body))
    monkeypatch.setattr(ollama_module, "OllamaProvider", lambda *a, **k: LocalModel())
    monkeypatch.setattr("app.observability._default_budget_seconds", 90.0)
    monkeypatch.setenv("GETNET_ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fb.sqlite3"))
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        token = client.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
        chat = client.post("/api/chat", json={"message": "Olá", "user_id": "cliente1988"},
                           headers={"Authorization": f"Bearer {token}"}).json()
    assert health["cloud_status"]["fallback_active"] is True
    assert health["llm_provider"]["provider"] == "ollama"
    assert any(str(t).startswith("llm_fallback_provider:ollama:llm_key_rejected") for t in chat["trace"])
