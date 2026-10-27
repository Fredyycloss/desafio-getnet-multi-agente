
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import main


class FakeChatService:
    def __init__(self, documents):
        pass

    def answer(self, message, user_id):
        return {
            "answer": "Resposta de teste",
            "intent": "product_information",
            "agent": "knowledge_agent",
            "confidence": 0.9,
            "sources": [],
            "handoff": False,
            "trace": ["guardrails", "router_agent", "knowledge_agent"],
        }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "load_documents", lambda: [])
    monkeypatch.setattr(main, "ChatService", FakeChatService)

    with TestClient(main.app) as test_client:
        yield test_client


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_accepts_valid_message(client):
    response = client.post(
        "/api/chat",
        json={
            "message": "What is Getnet?",
            "user_id": "test-user",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Resposta de teste"
    assert body["agent"] == "knowledge_agent"
    assert body["confidence"] == 0.9


def test_chat_rejects_blank_message(client):
    response = client.post(
        "/api/chat",
        json={"message": "   ", "user_id": "test-user"},
    )

    assert response.status_code == 422


def test_chat_rejects_missing_message(client):
    response = client.post(
        "/api/chat",
        json={"user_id": "test-user"},
    )

    assert response.status_code == 422


def test_knowledge_sources_returns_empty_list(client):
    response = client.get("/api/knowledge/sources")

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["sources"] == []
