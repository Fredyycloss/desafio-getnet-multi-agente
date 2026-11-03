import pytest

from app.agents.guardrails import inspect_message


@pytest.mark.parametrize("message,language", [
    ("Quero falar com uma pessoa.", "pt"),
    ("Quero um atendente, por favor.", "pt"),
    ("Não quero falar com robô.", "pt"),
    ("Preciso de atendimento humano.", "pt"),
    ("Transfira para alguém.", "pt"),
    ("Quero falar com um funcionário.", "pt"),
    ("I want a human agent.", "en"),
    ("I don't want to talk to a bot.", "en"),
    ("Please transfer me to a person.", "en"),
])
def test_explicit_human_requests_are_detected(message, language):
    result = inspect_message(message, language)

    assert result["blocked"] is False
    assert result["handoff"] is True
    assert result["reason"] == "human_requested"
