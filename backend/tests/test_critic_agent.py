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


class SeverityCriticModel:
    model = "severity-test"

    def __init__(self, verdict):
        self.verdict = verdict

    def chat(self, messages, tools=None, **kwargs):
        props = kwargs["json_schema"]["properties"]["issues"]["items"]
        assert props["required"] == ["problem", "material"]
        return {"message": {"content": __import__("json").dumps(self.verdict)}}


def test_minor_issues_do_not_reject_even_if_the_model_says_so(monkeypatch):
    monkeypatch.setenv("CRITIC_STRICTNESS", "material")
    model = SeverityCriticModel({"approved": False, "issues": [{"problem": "year omitted, acceptable", "material": False}]})
    result = CriticAgent(model, required=True).review("Funciona até 15/01.", "pt", [{"text": "A partir de 15/01"}], user_message="Até quando?")
    assert result["approved"] is True and result["issues"] == []
    assert result["minor_issues"] == ["year omitted, acceptable"] and result["model_verdict_overridden"] is True


def test_one_material_issue_rejects_even_if_the_model_approves(monkeypatch):
    monkeypatch.setenv("CRITIC_STRICTNESS", "material")
    model = SeverityCriticModel({"approved": True, "issues": [{"problem": "fee 1.99% not in evidence", "material": True},
                                                               {"problem": "tone", "material": False}]})
    result = CriticAgent(model, required=True).review("A taxa é 1,99%.", "pt", [{"text": "Taxas sob consulta"}], user_message="Qual a taxa?")
    assert result["approved"] is False and result["issues"] == ["fee 1.99% not in evidence"]


def test_strict_mode_blocks_on_any_issue(monkeypatch):
    monkeypatch.setenv("CRITIC_STRICTNESS", "strict")
    model = SeverityCriticModel({"approved": True, "issues": [{"problem": "missing caveat", "material": False}]})
    result = CriticAgent(model, required=True).review("Sim.", "pt", [{"text": "Sim"}], user_message="Pode?")
    assert result["approved"] is False
