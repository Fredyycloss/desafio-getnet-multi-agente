from __future__ import annotations

from .context_intelligence import ContextAssessment

ROUTINE_TOOLS = {
    "knowledge_specialist",
    "customer_support_specialist",
    "payments_specialist",
    "web_research_specialist",
}


class PolicyGate:
    """Applies deterministic controls without allowing a model to downgrade known hazards.

    Order: deterministic hazard -> alert; model "critical" -> alert;
    model "potentially_dangerous"/"ambiguous" -> safety clarification menu;
    other uncertainty -> topic menu; human request -> handoff; else continue.
    """

    def apply(self, assessment: dict, deterministic_risk: dict, *, contextual_model_available: bool = True) -> dict:
        parsed = ContextAssessment.model_validate(assessment)
        if deterministic_risk.get("requires_handoff"):
            if deterministic_risk.get("severity") == "critical":
                return {
                    "action": "safety_handoff",
                    "blocked_tools": sorted(ROUTINE_TOOLS),
                    "reason": deterministic_risk["reason"],
                }
            if parsed.figurative_language or parsed.needs_clarification:
                return {
                    "action": "ambiguous_safety_handoff",
                    "blocked_tools": sorted(ROUTINE_TOOLS),
                    "reason": "ambiguous_hazard_requires_human",
                }
            return {
                "action": "safety_handoff",
                "blocked_tools": sorted(ROUTINE_TOOLS),
                "reason": deterministic_risk["reason"],
            }
        if not contextual_model_available:
            return {"action": "continue", "blocked_tools": [], "reason": None}
        # Model-only safety signals. Without a deterministic hazard, only a
        # "critical" reading raises the alert; "potentially_dangerous" or
        # "ambiguous" (or a safety_handoff recommendation below critical) asks
        # the customer with a menu that offers "real physical risk" and a human.
        if parsed.risk_level == "critical":
            return {
                "action": "contextual_safety_handoff",
                "blocked_tools": sorted(ROUTINE_TOOLS),
                "reason": "contextual_risk_assessment",
            }
        if parsed.risk_level in {"potentially_dangerous", "ambiguous"} or parsed.recommended_action == "safety_handoff":
            return {
                "action": "clarify",
                "blocked_tools": sorted(ROUTINE_TOOLS),
                "reason": "contextual_safety_ambiguity",
                "safety_menu": True,
            }
        if (
            parsed.needs_clarification
            or parsed.recommended_action == "clarify"
            or parsed.recommended_destination == "clarification"
            or parsed.ambiguity_level == "high"
            or parsed.confidence < 0.55
        ):
            return {
                "action": "clarify",
                "blocked_tools": sorted(ROUTINE_TOOLS),
                "reason": "contextual_ambiguity",
            }
        if parsed.needs_human or parsed.recommended_action == "human_handoff":
            return {
                "action": "human_handoff",
                "blocked_tools": sorted(ROUTINE_TOOLS),
                "reason": "contextual_human_request",
            }
        return {
            "action": "continue",
            "blocked_tools": [],
            "reason": None,
        }
