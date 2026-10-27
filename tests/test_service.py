
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import service as service_module


class FakeRouter:
    def __init__(self):
        pass

    def route(self, message):
        if "maquininha" in message.lower():
            return "customer_support"
        return "knowledge"


class FakeKnowledge:
    name = "knowledge_agent"

    def __init__(self, documents):
        pass

    def run(self, message):
        return {
            "answer": "Informação sobre produto",
            "confidence": 0.9,
            "sources": [],
            "trace": ["knowledge_agent"],
        }


class FakeSupport:
    name = "customer_support_agent"

    def __init__(self):
        pass

    def run(self, message, user_id):
        return {
            "answer": f"Suporte para {user_id}",
            "confidence": 0.95,
            "sources": [],
            "trace": ["customer_support_agent"],
            "tool_result": {"status": "simulated"},
        }


class FakeEscalation:
    def __init__(self):
        pass

    def run(self, reason):
        return {
            "answer": "Encaminhado para atendimento humano",
            "confidence": 0.8,
            "sources": [],
            "handoff": True,
            "trace": ["escalation_agent"],
            "handoff_reason": reason,
        }


def make_service(monkeypatch):
    monkeypatch.setattr(
        service_module, "inspect_message",
        lambda message: {"blocked": False, "handoff": False},
    )
    monkeypatch.setattr(service_module, "RouterAgent", FakeRouter)
    monkeypatch.setattr(service_module, "KnowledgeAgent", FakeKnowledge)
    monkeypatch.setattr(service_module, "CustomerSupportAgent", FakeSupport)
    monkeypatch.setattr(service_module, "EscalationAgent", FakeEscalation)

    return service_module.ChatService([])


def test_service_routes_product_question_to_knowledge(monkeypatch):
    service = make_service(monkeypatch)

    result = service.answer("Tell me about Getnet products", "user-1")

    assert result["agent"] == "knowledge_agent"
    assert result["intent"] == "product_information"
    assert result["answer"] == "Informação sobre produto"


def test_service_routes_terminal_issue_to_support(monkeypatch):
    service = make_service(monkeypatch)

    result = service.answer("Minha maquininha não conecta", "user-2")

    assert result["agent"] == "customer_support_agent"
    assert result["intent"] == "customer_support"
    assert result["answer"] == "Suporte para user-2"
    assert result["tool_result"]["status"] == "simulated"
