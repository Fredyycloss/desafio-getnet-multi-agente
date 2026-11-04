"""Stage A: PolicyGate ordering, D3/D4 flows, no false safety alert, datasets and leak checks."""
import json
import re
import unicodedata
from pathlib import Path

import pytest

from app.agents.context_intelligence import ContextIntelligence
from app.agents.policy_gate import PolicyGate
from app.agents.risk_assessment_agent import RiskAssessmentAgent
from app.agents.supervisor_agent import SupervisorAgent
from tests.test_agents_and_orchestration import build_supervisor, context_assessment

EVAL_DIR = Path(__file__).parents[1] / "app" / "evaluation"
AGENTS_DIR = Path(__file__).parents[1] / "app" / "agents"
VAGUE = "Minha máquina está estranha e não sei o que está acontecendo."
NO_RISK = {"requires_handoff": False}


def load(split: str) -> list[dict]:
    return json.loads((EVAL_DIR / f"context_scenarios_{split}.json").read_text(encoding="utf-8"))


class FixedContextModel:
    """Transport fake: CI returns a fixed assessment; the Critic approves."""
    model = "scripted-test-model"

    def __init__(self, assessment: dict):
        self.assessment = assessment
        self.purposes: list[str] = []

    def chat(self, messages, tools=None, *, json_mode=False, json_schema=None, think=None,
             temperature=0.0, max_tokens=None, purpose="chat"):
        self.purposes.append(purpose)
        if purpose == "context_intelligence":
            return {"message": {"content": json.dumps(self.assessment)}}
        if json_schema is not None and "approved" in json_schema.get("properties", {}):
            return {"message": {"content": json.dumps({"approved": True, "issues": []})}}
        return {"message": {"content": "FINAL"}}


# -- PolicyGate ordering ---------------------------------------------------------

def test_model_critical_without_deterministic_hazard_raises_alert():
    result = PolicyGate().apply(context_assessment(risk_level="critical"), NO_RISK)
    assert result["action"] == "contextual_safety_handoff"


@pytest.mark.parametrize("risk", ["potentially_dangerous", "ambiguous"])
def test_model_possible_danger_without_deterministic_hazard_asks_with_safety_menu(risk):
    result = PolicyGate().apply(
        context_assessment(risk_level=risk, recommended_action="safety_handoff",
                           recommended_destination="safety_policy"), NO_RISK)
    assert result["action"] == "clarify"
    assert result["safety_menu"] is True


def test_deterministic_hazard_still_alerts_even_if_model_says_safe():
    risk = RiskAssessmentAgent().assess("A bateria da maquininha está estufada.", [], "pt")
    result = PolicyGate().apply(context_assessment(), risk)
    assert result["action"] == "safety_handoff"


# -- D3: vague message -> menu with physical risk + human, selection by number and text ---

def _d3_model():
    return FixedContextModel(context_assessment(
        intent="unclear terminal issue", risk_level="ambiguous", ambiguity_level="high",
        needs_clarification=True, recommended_agents=["customer_support_specialist"],
        recommended_action="safety_handoff", recommended_destination="safety_policy", confidence=0.5))


def test_d3_vague_message_gets_menu_with_physical_risk_and_human_not_an_alert(db, documents):
    supervisor = build_supervisor(db, documents, _d3_model())
    result = supervisor.run(message=VAGUE, user_id="cliente1988", session_id="d3", language="pt",
                            history=[], trace_id="d3")
    ids = [option["id"] for option in result["clarification_options"]]
    assert result["orchestration_mode"] == "context_policy_clarification"
    assert result["handoff"] is False
    assert ids[0] == "literal_hazard" and ids[-1] == "human_support"
    assert "terminal_connection" in ids


@pytest.mark.parametrize("reply", ["2", "Problemas de conexão"])
def test_d3_selection_by_number_or_text_preserves_context(db, documents, reply):
    first = build_supervisor(db, documents, _d3_model()).run(
        message=VAGUE, user_id="cliente1988", session_id="d3s", language="pt", history=[], trace_id="d3a")
    history = [{"role": "user", "content": VAGUE},
               {"role": "assistant", "content": first["answer"], "clarification_options": first["clarification_options"]}]
    # After the menu the model sees a short reply; even if it stays unsure, the selection resolves it.
    second = build_supervisor(db, documents, _d3_model()).run(
        message=reply, user_id="cliente1988", session_id="d3s", language="pt", history=history, trace_id="d3b")
    assert second["intent"] == "customer_support_clarification"
    assert second["handoff"] is False
    assert "context_intelligence" in second["trace"]


# -- D4: subject change during a menu ---------------------------------------------

def test_d4_subject_change_during_menu_is_a_new_request(db, documents):
    first = build_supervisor(db, documents, _d3_model()).run(
        message=VAGUE, user_id="cliente1988", session_id="d4", language="pt", history=[], trace_id="d4a")
    history = [{"role": "user", "content": VAGUE},
               {"role": "assistant", "content": first["answer"], "clarification_options": first["clarification_options"]}]
    change = "Na verdade, quero saber sobre pagamentos por Pix e problemas de conexão em geral, qual a taxa?"
    assert SupervisorAgent._selected_clarification_option(change, history) is None
    model = FixedContextModel(context_assessment())
    result = build_supervisor(db, documents, model).run(
        message=change, user_id="cliente1988", session_id="d4", language="pt", history=history, trace_id="d4b")
    assert "tool:knowledge_specialist" in result["trace"]
    assert result["intent"] not in {"customer_support_clarification", "knowledge_clarification"}


# -- "transaction decline error" goes to Payments, never to a safety alert --------

def test_transaction_decline_error_routes_to_payments_without_alert(db, documents):
    message = "transaction decline error"
    assert RiskAssessmentAgent().assess(message, [], "en")["requires_handoff"] is False
    model = FixedContextModel(context_assessment(
        intent="declined transaction", recommended_agents=["payments_specialist"],
        recommended_destination="payments_specialist"))
    result = build_supervisor(db, documents, model).run(
        message=message, user_id="cliente1988", session_id="decl", language="en", history=[], trace_id="decl")
    assert "tool:payments_specialist" in result["trace"]
    assert result["orchestration_mode"] != "safety_override"
    assert result["handoff"] is False


def test_model_overcautious_on_decline_error_gets_menu_not_alert(db, documents):
    model = FixedContextModel(context_assessment(
        intent="declined transaction", risk_level="potentially_dangerous",
        recommended_action="safety_handoff", recommended_destination="safety_policy"))
    result = build_supervisor(db, documents, model).run(
        message="transaction decline error", user_id="cliente1988", session_id="decl2", language="en",
        history=[], trace_id="decl2")
    assert result["orchestration_mode"] == "context_policy_clarification"
    assert result["handoff"] is False


# -- Zero safety false negatives ----------------------------------------------------

def _decide(case: dict, model_assessment: dict) -> str:
    controlled = ContextIntelligence._apply_deterministic_context_controls(
        {**context_assessment(), **model_assessment}, case["message"], case.get("history", []), "pt")
    deterministic = RiskAssessmentAgent().assess(case["message"], case.get("history", []), "pt")
    return PolicyGate().apply(controlled, deterministic)["action"]


DANGEROUS = {"potentially_dangerous", "critical"}


@pytest.mark.parametrize("case", [c for c in load("dev") if c["expected_risk"] in DANGEROUS], ids=lambda c: c["id"])
def test_dev_hazards_are_caught_even_if_the_model_says_safe(case):
    # Deterministic layer alone: a model that downplays the hazard cannot cause a false negative.
    adversarial = {"risk_level": "safe", "figurative_language": True, "recommended_action": "route_to_agent"}
    assert _decide(case, adversarial) in {"safety_handoff", "ambiguous_safety_handoff"}


@pytest.mark.parametrize("case", [c for c in load("dev") + load("heldout_v1") + load("heldout_v2") if c["expected_risk"] in DANGEROUS],
                         ids=lambda c: c["id"])
def test_policy_never_drops_a_hazard_the_model_reports(case):
    # Held-out is NOT used to tune rules: here the model reports the labelled risk and the
    # policy must keep it (alert or safety menu). Real model accuracy is measured live.
    honest = {"risk_level": case["expected_risk"], "recommended_action": "safety_handoff",
              "recommended_destination": "safety_policy"}
    assert _decide(case, honest) in {"safety_handoff", "ambiguous_safety_handoff", "contextual_safety_handoff", "clarify"}


# -- Datasets and evaluation leak ----------------------------------------------------

def test_heldout_v2_is_large_disjoint_and_records_origin():
    seen = {c["message"] for c in load("dev") + load("heldout_v1")}
    v2 = load("heldout_v2")
    assert len(v2) >= 100 and len({c["id"] for c in v2}) == len(v2)
    assert not seen & {c["message"] for c in v2}
    assert all(c.get("origin") for c in v2)
    assert {c["origin"].split(" ")[0].split(":")[0].rstrip(";") for c in v2} == {"manual", "generated", "paraphrase"}


def test_heldout_dataset_is_large_disjoint_and_covers_new_categories():
    dev, heldout = load("dev"), load("heldout_v1")
    assert len(heldout) >= 40
    assert len({c["id"] for c in heldout}) == len(heldout)
    assert not {c["message"] for c in dev} & {c["message"] for c in heldout}
    assert {"continuation", "topic_change", "irony_sarcasm", "prompt_injection", "contradictory",
            "real_accident", "human_request", "ambiguous"} <= {c["category"] for c in heldout}
    allowed_actions = {"continue", "clarify", "safety_handoff", "human_handoff"}
    assert all(c["expected_action"] in allowed_actions for c in heldout)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# The mission prescribes this general idiom pattern ("pegando fogo de tanto
# movimento|venda|cliente|gente"); it is the only allowed overlap.
SANCTIONED_GRAMS = {"pegando fogo de tanto", "fogo de tanto movimento"}


@pytest.mark.parametrize("module", ["context_intelligence.py", "risk_assessment_agent.py", "policy_gate.py",
                                    "clarification.py"])
def test_no_dataset_phrase_is_copied_into_routing_code(module):
    source = _norm((AGENTS_DIR / module).read_text(encoding="utf-8"))
    leaked = []
    for case in load("dev") + load("heldout_v1") + load("heldout_v2"):
        words = _norm(case["message"]).split()
        for i in range(len(words) - 3):
            gram = " ".join(words[i:i + 4])
            if gram in source and gram not in SANCTIONED_GRAMS:
                leaked.append((case["id"], gram))
    assert not leaked, leaked
