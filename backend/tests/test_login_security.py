"""Login lockout / rate limit (customer and operator) and DEMO_MODE=false behaviour."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "login.sqlite3"))
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "120")
    monkeypatch.setenv("LOGIN_MAX_REQUESTS_PER_MINUTE", "1000")
    with TestClient(app) as c:
        yield c


def _login(client, user, pin):
    return client.post("/api/auth/demo-login", json={"user_id": user, "pin": pin})


def test_customer_account_locks_after_repeated_failures(client):
    for _ in range(3):
        assert _login(client, "cliente1988", "0000").status_code == 401
    locked = _login(client, "cliente1988", "1988")  # right PIN, but the account is locked
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    assert _login(client, "demo-user-001", "0001").status_code == 200  # other accounts unaffected


def test_success_clears_failures(client):
    assert _login(client, "cliente1988", "0000").status_code == 401
    assert _login(client, "cliente1988", "0000").status_code == 401
    assert _login(client, "cliente1988", "1988").status_code == 200
    assert _login(client, "cliente1988", "0000").status_code == 401
    assert _login(client, "cliente1988", "1988").status_code == 200


def test_unknown_and_known_accounts_get_the_same_answer(client):
    a, b = _login(client, "nobody-here", "1234"), _login(client, "cliente1988", "1234")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_operator_login_locks_after_repeated_failures(client):
    for _ in range(3):
        assert client.post("/api/operator/login", json={"username": "ana.operadora", "password": "x"}).status_code == 401
    r = client.post("/api/operator/login", json={"username": "ana.operadora", "password": "demo-ana-2026"})
    assert r.status_code == 429
    audit_token = client.post("/api/operator/login", json={"username": "bruno.supervisor", "password": "demo-bruno-2026"}).json()["access_token"]
    audit = client.get("/api/operator/audit", headers={"Authorization": f"Bearer {audit_token}"}).json()
    outcomes = [e["outcome"] for e in audit["items"] if e["operator"] == "ana.operadora"]
    assert "failed" in outcomes and "locked" in outcomes


def test_address_ceiling_stops_password_spraying(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "spray.sqlite3"))
    monkeypatch.setenv("LOGIN_MAX_REQUESTS_PER_MINUTE", "5")
    with TestClient(app) as c:
        codes = [_login(c, f"user-{i}", "1111").status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]


def test_non_demo_mode_requires_secret_and_hides_user_list(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "prod.sqlite3"))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        with TestClient(app):
            pass
    from app.auth import _scrypt
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"cliente1988": {"salt": "ab" * 16, "hash": _scrypt("s3cret-pin", "ab" * 16)}}))
    monkeypatch.setenv("AUTH_SECRET", "x" * 40)
    monkeypatch.setenv("CUSTOMER_CREDENTIALS_FILE", str(creds))
    with TestClient(app) as c:
        assert c.get("/api/auth/demo-users").status_code == 404
        assert _login(c, "cliente1988", "1988").status_code == 401  # public demo PIN no longer works
        assert _login(c, "cliente1988", "s3cret-pin").status_code == 200
        assert c.post("/api/operator/login", json={"username": "ana.operadora", "password": "demo-ana-2026"}).status_code == 401


def test_chat_is_rate_limited_per_customer(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "chat.sqlite3"))
    monkeypatch.setenv("CHAT_MAX_REQUESTS_PER_MINUTE", "2")
    with TestClient(app) as c:
        def chat(user, pin):
            token = _login(c, user, pin).json()["access_token"]
            return c.post("/api/chat", json={"message": "Oi", "user_id": user}, headers={"Authorization": f"Bearer {token}"})
        assert [chat("cliente1988", "1988").status_code for _ in range(3)] == [200, 200, 429]
        assert chat("demo-user-001", "0001").status_code == 200  # limit is per customer
