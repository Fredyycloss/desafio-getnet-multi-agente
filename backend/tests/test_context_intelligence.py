import json

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.context_intelligence import ContextAssessment, ContextIntelligence
from app.agents.policy_gate import PolicyGate, ROUTINE_TOOLS
from app.infra.ollama_client import OllamaUnavailable


def valid_assessment(**overrides):
    return {
        "intent": "technical_support",
        "context": "The user reports a device problem.",
        "emotional_state": None,
        "figurative_language": False,
        "figurative_signals": [],
        "ambiguity_level": "low",
        "risk_level": "safe",
        "confidence": 0.95,
        "needs_clarification": False,
        "clarification_question": None,
        "needs_human": False,
        "recommended_agents": ["customer_support_specialist"],
        "recommended_destination": "customer_support_specialist",
        "recommended_action": "route_to_agent",
        "operational_reason": "Terminal troubleshooting requires the support specialist.",
        "blocked_tools": [],
        **overrides,
    }


class ContextModel:
    model = "qwen2.5:3b"

    def __init__(self, content):
        self.content = content
        self.messages = None

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None, temperature=0.0, max_tokens=None, purpose="chat"):
        self.messages = messages
        assert json_mode is False
        assert json_schema["type"] == "object"
        assert "risk_level" in json_schema["required"]
        assert think is False
        return {"message": {"content": self.content}}


def test_context_intelligence_uses_current_message_history_and_validates_json():
    model = ContextModel(json.dumps(valid_assessment()))
    history = [{"role": "user", "content": "The terminal has been offline since yesterday."}]

    result, mode = ContextIntelligence(model).assess(
        "Agora está pior.", history, "pt", "trace-context"
    )

    sent = json.loads(model.messages[1]["content"])
    assert sent["current_message"] == "Agora está pior."
    assert sent["recent_history"] == history
    assert mode == "llm_context_intelligence"
    assert ContextAssessment.model_validate(result).intent == "technical_support"


def test_context_schema_contains_action_destination_and_operational_reason():
    schema = ContextAssessment.model_json_schema()

    assert {"recommended_action", "recommended_destination", "operational_reason"} <= set(schema["properties"])
    assert {"recommended_action", "recommended_destination", "operational_reason"} <= set(schema["required"])


def test_context_intelligence_receives_the_selected_clarification_topic():
    model = ContextModel(json.dumps(valid_assessment()))
    ContextIntelligence(model).assess(
        "1", [{"role": "assistant", "content": "Choose a topic: 1. Connection"}], "pt", "trace-selection",
        selected_option="terminal_connection",
    )

    sent = json.loads(model.messages[1]["content"])
    assert sent["selected_option"] == "terminal_connection"


def test_context_intelligence_rejects_malformed_model_output():
    with pytest.raises(OllamaUnavailable):
        ContextIntelligence(ContextModel('{"risk_level":"safe"}')).assess(
            "Minha máquina não conecta.", [], "pt", "trace-invalid"
        )


@pytest.mark.parametrize("missing", ["recommended_destination", "recommended_action", "operational_reason"])
def test_context_intelligence_rejects_missing_required_routing_fields(missing):
    incomplete = valid_assessment()
    incomplete.pop(missing)
    with pytest.raises(OllamaUnavailable):
        ContextIntelligence(ContextModel(json.dumps(incomplete))).assess(
            "Minha máquina não conecta.", [], "pt", "trace-missing-routing"
        )


def test_deterministic_hazard_cannot_be_downgraded_by_model():
    gate = PolicyGate()
    result = gate.apply(
        valid_assessment(),
        {"requires_handoff": True, "severity": "critical", "reason": "physical_safety_critical"},
    )

    assert result["action"] == "safety_handoff"
    assert set(result["blocked_tools"]) == ROUTINE_TOOLS


def test_literal_critical_hazard_overrides_model_figurative_guess():
    result = PolicyGate().apply(
        valid_assessment(figurative_language=True, risk_level="ambiguous"),
        {"requires_handoff": True, "severity": "critical", "reason": "physical_safety_critical"},
    )

    assert result["action"] == "safety_handoff"


def test_figurative_hazard_still_blocks_tools_and_routes_to_human():
    result = PolicyGate().apply(
        valid_assessment(
            figurative_language=True,
            ambiguity_level="medium",
            risk_level="ambiguous",
        ),
        {"requires_handoff": True, "severity": "high", "reason": "physical_safety_high"},
    )

    assert result["action"] == "ambiguous_safety_handoff"
    assert set(result["blocked_tools"]) == ROUTINE_TOOLS


def test_context_advisories_do_not_route_when_model_is_unavailable():
    result = PolicyGate().apply(
        valid_assessment(
            risk_level="critical",
            ambiguity_level="high",
            confidence=0.1,
        ),
        {"requires_handoff": False},
        contextual_model_available=False,
    )

    assert result == {"action": "continue", "blocked_tools": [], "reason": None}


def test_ambiguous_context_requires_clarification_and_blocks_routine_tools():
    result = PolicyGate().apply(
        valid_assessment(risk_level="ambiguous", ambiguity_level="high"),
        {"requires_handoff": False},
    )

    assert result["action"] == "clarify"
    assert set(result["blocked_tools"]) == ROUTINE_TOOLS


def test_context_action_recommendation_can_request_a_clarification():
    result = PolicyGate().apply(
        valid_assessment(recommended_action="clarify", recommended_destination="clarification"),
        {"requires_handoff": False},
    )

    assert result["action"] == "clarify"
    assert set(result["blocked_tools"]) == ROUTINE_TOOLS


def test_uncertainty_precedes_contextual_human_suggestion():
    result = PolicyGate().apply(
        valid_assessment(
            risk_level="ambiguous",
            ambiguity_level="high",
            needs_clarification=True,
            needs_human=True,
        ),
        {"requires_handoff": False},
    )

    assert result["action"] == "clarify"


def test_context_assessment_rejects_unallowlisted_agents():
    with pytest.raises(ValidationError):
        ContextAssessment.model_validate(valid_assessment(recommended_agents=["shell"]))


def test_context_dataset_covers_required_portuguese_scenarios():
    dataset = json.loads(
        (Path(__file__).parents[1] / "app" / "evaluation" / "context_scenarios_dev.json").read_text(
            encoding="utf-8"
        )
    )
    categories = {case["category"] for case in dataset}

    assert len(dataset) >= 20
    assert len({case["id"] for case in dataset}) == len(dataset)
    assert {
        "common_technical",
        "real_accident",
        "figurative_or_ambiguous",
        "irony_sarcasm",
        "emotional_complaint",
        "possible_trojan",
        "contradictory",
        "history_only_risk",
        "human_request",
    } <= categories


def test_context_model_is_asked_only_for_compact_routing_fields():
    from app.agents.context_intelligence import ContextModelOutput

    compact = {key: valid_assessment()[key] for key in ContextModelOutput.model_fields}
    model = ContextModel(json.dumps(compact))
    history = [{"role": "user", "content": "x" * 1000}] * 10

    result, mode = ContextIntelligence(model).assess("Minha máquina não conecta.", history, "pt", "trace-compact")

    sent = json.loads(model.messages[1]["content"])
    assert len(sent["recent_history"]) == 6
    assert all(len(item["content"]) <= 400 for item in sent["recent_history"])
    assert mode == "llm_context_intelligence"
    # Fields the model no longer emits are filled with neutral defaults.
    assert result["blocked_tools"] == [] and result["emotional_state"] is None
    assert ContextAssessment.model_validate(result).recommended_destination == "customer_support_specialist"


def test_context_schema_sent_to_model_omits_unused_fields():
    from app.agents.context_intelligence import context_output_schema

    schema = context_output_schema()
    assert {"recommended_action", "recommended_destination", "operational_reason", "risk_level"} <= set(schema["required"])
    for unused in ("context", "emotional_state", "figurative_signals", "clarification_question", "blocked_tools"):
        assert unused not in schema["properties"]
