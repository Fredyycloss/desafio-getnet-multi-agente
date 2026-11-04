"""CRITIC_CHALLENGE_MODE: test-only corrupted first drafts exercise Critic → re-plan → handoff."""
from __future__ import annotations

import pytest

from app.agents import critic_challenge
from app.agents.critic_agent import deterministic_issues
from app.main import app
from tests.conftest import AutoAuthClient as TestClient

QUESTION = {"message": "A Get Lite tem aluguel mensal?", "user_id": "cliente1988"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_CRAWL_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("kind", sorted(critic_challenge.KINDS))
def test_every_kind_changes_the_draft(kind):
    draft = "A Get Lite não tem aluguel mensal [1]. A taxa é 2,5%."
    assert critic_challenge.corrupt(draft, kind, "pt") != draft


def test_deterministic_checks_catch_secret_and_citation_corruptions():
    draft = "A Get Lite não tem aluguel mensal [1]."
    assert "asks_customer_for_secret" in deterministic_issues(critic_challenge.corrupt(draft, "secret_request", "pt"), [{}])
    assert any(i.startswith("citation_without_source") for i in
               deterministic_issues(critic_challenge.corrupt(draft, "wrong_citation", "pt"), [{}]))


def test_header_is_ignored_unless_mode_enabled(client, monkeypatch):
    monkeypatch.delenv("CRITIC_CHALLENGE_MODE", raising=False)
    data = client.post("/api/chat", json=QUESTION, headers={"X-Critic-Challenge": "secret_request"}).json()
    assert not any(t.startswith("critic_challenge_injected") for t in data["trace"])
    assert "senha" not in data["answer"].lower()


@pytest.mark.parametrize("kind", ["secret_request", "wrong_citation"])
def test_corrupted_draft_never_reaches_the_customer(client, monkeypatch, kind):
    monkeypatch.setenv("CRITIC_CHALLENGE_MODE", "true")
    data = client.post("/api/chat", json=QUESTION, headers={"X-Critic-Challenge": kind}).json()
    assert f"critic_challenge_injected:{kind}" in data["trace"]
    assert "informe a sua senha" not in data["answer"].lower()
    assert "[9]" not in data["answer"]
    # The Critic rejected the first draft; the result is a re-planned answer or a hand-off.
    assert any(t.startswith("critic_rejected") or t.startswith("replan") or "handoff" in t for t in data["trace"]), data["trace"]


def test_unknown_kind_is_ignored(client, monkeypatch):
    monkeypatch.setenv("CRITIC_CHALLENGE_MODE", "true")
    data = client.post("/api/chat", json=QUESTION, headers={"X-Critic-Challenge": "drop_tables"}).json()
    assert not any(t.startswith("critic_challenge_injected") for t in data["trace"])
