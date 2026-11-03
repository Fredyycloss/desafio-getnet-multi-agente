from app.agents.critic_agent import CriticAgent


class InvalidCriticModel:
    model = "invalid-test-response"

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        return {"message": {"content": "not valid JSON"}}


def test_required_critic_never_silently_approves_when_structured_review_fails():
    result = CriticAgent(InvalidCriticModel(), required=True).review(
        "The answer", "en", [{"source": "official evidence"}], user_message="My question",
        conversation_context=[{"role": "user", "content": "Earlier context"}],
    )

    assert result["approved"] is False
    assert result["mode"] == "llm_critic_invalid"
    assert result["issues"] == ["critic_validation_unavailable"]


class ValidCriticModel:
    model = "valid-test-response"

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        assert json_mode is False
        assert {"approved", "issues"} <= set(json_schema["required"])
        # The Supervisor never used a rewritten answer; requesting one only cost tokens.
        assert "corrected_answer" not in json_schema["properties"]
        assert max_tokens is not None and max_tokens <= 80
        assert think is False
        assert temperature == 0.0
        return {"message": {"content": '{"approved":true,"issues":[],"corrected_answer":""}'}}


def test_critic_requests_deterministic_json_without_reasoning_output():
    result = CriticAgent(ValidCriticModel(), required=True).review(
        "Olá! Como posso ajudar?", "pt", [],
        user_message="Apenas cumprimente o cliente e pergunte como pode ajudar.",
    )

    assert result["approved"] is True
    assert result["mode"] == "llm_critic"


class MissingVerdictCriticModel:
    model = "missing-verdict-test-response"

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        return {"message": {"content": '{"issues":[],"corrected_answer":""}'}}


def test_critic_rejects_response_that_omits_required_verdict():
    result = CriticAgent(MissingVerdictCriticModel(), required=True).review(
        "The answer", "en", [], user_message="My question",
    )

    assert result["approved"] is False
    assert result["mode"] == "llm_critic_invalid"
