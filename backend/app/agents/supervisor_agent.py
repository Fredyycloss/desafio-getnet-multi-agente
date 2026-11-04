from __future__ import annotations

import logging
import time

from ..infra.database import Database
from ..infra.llm import LLMProvider, LLMTimeout, LLMUnavailable
from ..observability import stage
from .clarification import clarification_result
from .context_intelligence import ContextIntelligence, CONTEXT_MODES
from .critic_agent import CriticAgent
from .escalation_agent import EscalationAgent
from .knowledge_agent import KnowledgeAgent
from .policy_gate import PolicyGate
from .risk_assessment_agent import RiskAssessmentAgent
from .payments_agent import PaymentsAgent
from .support_agent import CustomerSupportAgent
from .web_research_agent import WebResearchAgent

from .supervisor.composer import ComposerMixin
from .supervisor.constants import (  # noqa: F401 - re-exported
    AGENT_ALIASES, FAST_PATH_AGENTS, FINAL_MARKER, HOME_TOPICS, PLANNER_CONTEXT_KEYS, SUPERVISOR_TOOLS, canonical_agent,
)
from .supervisor.fast_path import FastPathMixin
from .supervisor.menus import MenuMixin
from .supervisor.planner import PlannerMixin
from .supervisor.replanner import ReplanMixin

logger = logging.getLogger(__name__)


class SupervisorAgent(FastPathMixin, PlannerMixin, ReplanMixin, ComposerMixin, MenuMixin):
    """LLM-directed tool orchestration with bounded observe/re-plan cycles."""
    name = "supervisor_agent"
    MAX_TOOL_CALLS = 4
    MAX_PLANNING_ROUNDS = 3
    HISTORY_MESSAGES = 6
    HISTORY_CHARS = 500
    TOOL_CONTENT_CHARS = 2500

    def __init__(self, *, llm: LLMProvider | None, db: Database, knowledge: KnowledgeAgent,
                 support: CustomerSupportAgent, web: WebResearchAgent, risk: RiskAssessmentAgent,
                 escalation: EscalationAgent, critic: CriticAgent,
                 context_intelligence: ContextIntelligence | None = None,
                 llm_required: bool = False, payments: PaymentsAgent | None = None):
        self.llm, self.db, self.knowledge, self.support, self.web = llm, db, knowledge, support, web
        self.risk, self.escalation, self.critic = risk, escalation, critic
        self.payments = payments or PaymentsAgent(db, llm=support.llm)
        self.context_intelligence = context_intelligence or ContextIntelligence(llm)
        self.policy_gate = PolicyGate()
        self.llm_required = llm_required

    def run(self, *, message: str, user_id: str, session_id: str, language: str, history: list[dict], trace_id: str,
            selected_topic: str | None = None) -> dict:
        result = self._run(message=message, user_id=user_id, session_id=session_id, language=language,
                           history=history, trace_id=trace_id, selected_topic=selected_topic)
        # A configured model whose contextual pass failed means the turn was not
        # interpreted by the LLM: the response is degraded even if it is safe.
        if (self.llm and not result.get("degraded")
                and (result.get("context_assessment") or {}).get("assessment_mode") == "deterministic_fallback"):
            result["degraded"] = True
            result["degraded_reason"] = "context_llm_unavailable"
        result.setdefault("degraded", False)
        result.setdefault("degraded_reason", None)
        # Name the real cause when the cloud key was refused or ran out of credit.
        key_reason = getattr(self.llm, "key_failure_reason", None) if self.llm else None
        if key_reason and result["degraded"]:
            result["degraded_reason"] = key_reason
        if getattr(self.llm, "fallback_active", False):
            result["trace"] = [*result.get("trace", []), f"llm_fallback_provider:{self.llm.fallback.provider}:{self.llm.fallback_reason}"]
        return result

    def _run(self, *, message: str, user_id: str, session_id: str, language: str, history: list[dict], trace_id: str,
             selected_topic: str | None = None) -> dict:
        from .guardrails import inspect_message
        guard = inspect_message(message, language)
        if guard.get("blocked"):
            result = {"answer": guard["message"], "confidence": 1.0, "sources": [], "handoff": False}
            return self._pack(result, language, "sensitive_data_guardrail", ["supervisor_agent", "guardrails", "request_blocked"], "deterministic_guardrail", critic={"approved": True, "mode": "security_policy"}, trace_id=trace_id,
                              context_assessment={"risk_level": "blocked_sensitive_data", "source": "deterministic_guardrail"})

        # Context Intelligence is the first agent for every non-secret turn.
        # Secret disclosure is stopped by a deterministic privacy guard before any model sees it.
        selected_option = self._selected_clarification_option(message, history)
        assessment_error: LLMUnavailable | None = None
        try:
            with stage("context_intelligence", "agent"):
                assessment, assessment_mode = self.context_intelligence.assess(
                    message, history, language, trace_id, selected_option=selected_option or selected_topic
                )
        except LLMUnavailable as exc:
            assessment_error = exc
            with stage("context_intelligence_fallback", "agent"):
                assessment, assessment_mode = ContextIntelligence(None).assess(message, history, language, trace_id)
            logger.warning("context_llm_unavailable trace_id=%s error=%s", trace_id, str(exc))
        risk_message = message
        if selected_option == "figurative_expression":
            risk_message += " [customer confirmed a figurative expression]"
        with stage("risk_assessment", "agent"):
            risk = self.risk.assess(risk_message, history, language)
        if risk.get("requires_handoff"):
            with stage("human_handoff", "agent"):
                result = self.escalation.run(
                    reason=risk["reason"], language=language, user_id=user_id,
                    message=message, severity=risk["severity"], session_id=session_id,
                    safety_message=risk["message_template"], history=history,
                )
            assessment.update({"recommended_action": "safety_handoff", "recommended_destination": "safety_policy",
                               "operational_reason": risk["reason"], "assessment_mode": assessment_mode})
            if self.llm: assessment["model"] = self.llm.model; assessment["provider"] = getattr(self.llm, "provider", "unknown")
            return self._pack(
                result, language, "physical_safety",
                ["context_intelligence", assessment_mode, "supervisor_agent", *risk["trace"], *result["trace"]],
                "safety_override",
                critic={"approved": True, "mode": "safety_policy"},
                trace_id=trace_id,
                context_assessment={**assessment,
                    "risk_level": risk["severity"],
                    "source": "deterministic_risk_agent",
                    "rationale": risk["reason"],
                },
            )

        if guard.get("handoff") or selected_option == "human_support":
            reason = "human_requested_from_clarification" if selected_option == "human_support" else "human_requested"
            with stage("human_handoff", "agent"):
                result = self.escalation.run(reason=reason, language=language, user_id=user_id,
                                             message=message, session_id=session_id, history=history)
            assessment.update({"intent": "human_request", "needs_human": True,
                               "recommended_action": "human_handoff", "recommended_destination": "human_handoff",
                               "operational_reason": "Customer explicitly requested human support.",
                               "assessment_mode": assessment_mode})
            if self.llm: assessment["model"] = self.llm.model; assessment["provider"] = getattr(self.llm, "provider", "unknown")
            return self._pack(result, language, "human_handoff", ["context_intelligence", assessment_mode, "supervisor_agent", *result["trace"]], "direct_handoff", critic={"approved": True, "mode": "handoff_policy"}, trace_id=trace_id,
                              context_assessment={**assessment, "source": "context_intelligence_and_human_request"})

        if selected_option == "literal_hazard":
            with stage("human_handoff", "agent"):
                result = self.escalation.run(
                    reason="physical_hazard_confirmed_after_clarification",
                    language=language, user_id=user_id, message=message, severity="high",
                    session_id=session_id, history=history, safety_message=(
                    "Obrigado por confirmar o risco físico. Afaste-se do equipamento e não tente usá-lo ou consertá-lo. "
                    "Se houver fumaça, fogo, faíscas ou perigo imediato no Brasil, ligue para os Bombeiros no 193. "
                    "Protocolo: {protocol}. {availability}"
                    if language == "pt" else
                    "Thank you for confirming a physical hazard. Move away from the device and do not use or repair it. "
                    "If there is smoke, fire, sparking, or immediate danger, contact local emergency services. "
                    "Protocol: {protocol}. {availability}"
                    ),
                )
            return self._pack(
                result, language, "physical_safety",
                ["context_intelligence", assessment_mode, "supervisor_agent", "literal_hazard_confirmed", *result["trace"]],
                "safety_override", critic={"approved": True, "mode": "safety_policy"},
                trace_id=trace_id,
                context_assessment={**assessment, "risk_level": "high", "source": "user_clarification",
                                    "recommended_action": "safety_handoff", "recommended_destination": "safety_policy",
                                    "operational_reason": "Customer confirmed a current physical hazard.",
                                    "assessment_mode": assessment_mode},
            )

        if selected_option in {"figurative_expression", "getnet_topic"}:
            assessment.update({"risk_level": "safe", "needs_clarification": False,
                               "needs_human": False, "ambiguity_level": "low",
                               "confidence": max(float(assessment.get("confidence", 0)), 0.75),
                               "recommended_action": "route_to_agent", "recommended_destination": "supervisor"})

        if assessment_error and self.llm_required:
            raise assessment_error

        routing_message = self._routing_message(message, history, selected_option, language)
        topic_agent = None
        if selected_topic and not selected_option:
            # Explicit home-screen choice (after the deterministic risk check above): no clarification,
            # dispatch to the topic's specialist; customer data needs a logged-in customer.
            from ..auth import is_anonymous
            topic_agent = HOME_TOPICS[selected_topic]
            if topic_agent == "payments_specialist" and is_anonymous(user_id):
                topic_agent = "knowledge_specialist"
            assessment.update({"needs_clarification": False, "ambiguity_level": "low", "risk_level": "safe", "needs_human": False,
                               "confidence": max(float(assessment.get("confidence", 0)), 0.9),
                               "recommended_agents": [topic_agent], "recommended_action": "route_to_agent",
                               "recommended_destination": topic_agent, "selected_topic": selected_topic,
                               "operational_reason": "Customer selected a home-screen topic."})
        if selected_option and selected_option != "literal_hazard":
            # A topic selection resolves the previous menu ambiguity. Preserve the original
            # request and let the Supervisor select the relevant specialist on this turn.
            assessment["needs_clarification"] = False
            assessment["ambiguity_level"] = "low"
            assessment["risk_level"] = "safe"
            assessment["needs_human"] = False
            assessment["confidence"] = max(float(assessment.get("confidence", 0)), 0.75)
            assessment["recommended_action"] = "route_to_agent"
            assessment["recommended_destination"] = "supervisor"
            assessment["operational_reason"] = "Customer selected a topic; route with the preserved request context."

        with stage("policy_gate", "guardrail"):
            decision = self.policy_gate.apply(
                assessment, risk,
                contextual_model_available=assessment_mode in CONTEXT_MODES,
            )
        action_map = {
            "clarify": ("clarify", "clarification"),
            "human_handoff": ("human_handoff", "human_handoff"),
            "safety_handoff": ("safety_handoff", "safety_policy"),
            "ambiguous_safety_handoff": ("safety_handoff", "safety_policy"),
            "contextual_safety_handoff": ("safety_handoff", "safety_policy"),
            "continue": ("route_to_agent", "supervisor"),
        }
        recommended_action, recommended_destination = action_map[decision["action"]]
        if recommended_destination == "supervisor" and assessment.get("recommended_agents"):
            recommended_destination = assessment["recommended_agents"][0]
        assessment["recommended_action"] = recommended_action
        assessment["recommended_destination"] = recommended_destination
        assessment["operational_reason"] = decision.get("reason") or "Intent sufficiently clear for specialist routing."
        assessment["assessment_mode"] = assessment_mode
        if self.llm:
            assessment["model"] = self.llm.model; assessment["provider"] = getattr(self.llm, "provider", "unknown")
        assessment["policy_decision"] = decision
        context_trace = ["context_intelligence", assessment_mode, f"policy_gate:{decision['action']}"]
        if decision["action"] in {"safety_handoff", "ambiguous_safety_handoff", "contextual_safety_handoff", "human_handoff"}:
            is_safety = decision["action"] in {"safety_handoff", "ambiguous_safety_handoff", "contextual_safety_handoff"}
            uncertain_safety = decision["action"] == "ambiguous_safety_handoff"
            severity = (
                "critical" if (
                    decision["action"] == "safety_handoff" and risk["severity"] == "critical"
                ) or assessment["risk_level"] == "critical"
                else ("high" if is_safety else "normal")
            )
            reason = decision["reason"]
            if is_safety:
                safety_message = ((
                    "Não consigo confirmar se você está usando uma expressão figurada ou descrevendo um risco real. Não vou orientar procedimentos técnicos enquanto isso não estiver esclarecido. "
                    "Se houver fumaça, fogo, faíscas ou perigo imediato, afaste-se e ligue para os Bombeiros no 193. "
                    "Protocolo: {protocol}. {availability}"
                    if language == "pt" else
                    "I cannot confirm whether this is figurative language or a real hazard. I will not provide technical steps until this is clarified. "
                    "If there is smoke, fire, sparks, or immediate danger, move away and contact local emergency services. "
                    "Protocol: {protocol}. {availability}"
                ) if uncertain_safety else (
                    "A descrição pode indicar risco físico. Não continue usando nem tente reparar o equipamento enquanto isso não estiver esclarecido. "
                    "Se houver fumaça, fogo, faíscas ou perigo imediato no Brasil, afaste-se e ligue para os Bombeiros no 193. "
                    "Protocolo: {protocol}. {availability}"
                    if language == "pt" else
                    "Your description may indicate physical danger. Do not continue using or attempt to repair the device until this is clarified. "
                    "If there is smoke, fire, sparks, or immediate danger, move away and contact local emergency services. "
                    "Protocol: {protocol}. {availability}"
                ))
            else:
                safety_message = None
            with stage("human_handoff", "agent"):
                result = self.escalation.run(
                    reason=reason, language=language, user_id=user_id, message=message,
                    severity=severity, session_id=session_id, safety_message=safety_message,
                    history=history,
                )
            return self._pack(
                result, language, "physical_safety" if is_safety else "human_handoff",
                ["supervisor_agent", *context_trace, *result["trace"]],
                "safety_override" if is_safety else "context_policy_handoff",
                critic={"approved": True, "mode": "deterministic_policy"},
                trace_id=trace_id, context_assessment=assessment,
            )
        if decision["action"] == "clarify":
            result = clarification_result(
                language,
                contextual=assessment["risk_level"] == "ambiguous",
                safety=bool(decision.get("safety_menu")),
                intent=assessment.get("intent", ""),
                message=message,
            )
            assessment["recommended_destination"] = "clarification"
            assessment["operational_reason"] = "Intent or required safety context is unclear; topic selection requested."
            return self._pack(
                result, language, "clarification_required",
                ["supervisor_agent", *context_trace, "routine_tools_blocked"],
                "context_policy_clarification", critic={"approved": True, "mode": "deterministic_policy"},
                trace_id=trace_id, context_assessment=assessment,
            )

        if selected_option in {
            "terminal_support", "terminal_connection", "terminal_sales", "terminal_defect",
            "sales_payments", "payment_status", "settlement_timing", "declined_transaction",
        }:
            assessment.update({
                "needs_clarification": True,
                "recommended_action": "clarify",
                "recommended_destination": "customer_support_specialist",
                "operational_reason": "Customer selected a support topic; the specialist is collecting the details needed to continue.",
            })
            result = self.support.request_selected_topic_details(selected_option, language)
            return self._pack(
                result, language, "customer_support_clarification",
                ["context_intelligence", assessment_mode, "policy_gate:continue", "supervisor_agent", *result["trace"]],
                "specialist_intake_clarification",
                critic={"approved": True, "mode": "curated_intake_template"},
                trace_id=trace_id, context_assessment=assessment,
            )

        if selected_option in {"products_fees", "getnet_topic", "figurative_expression"}:
            assessment.update({
                "needs_clarification": True,
                "recommended_action": "clarify",
                "recommended_destination": "knowledge_specialist",
                "operational_reason": "Customer selected a Getnet topic; the specialist is collecting a precise subject before retrieval.",
            })
            result = self.knowledge.request_selected_topic_details(selected_option, language)
            return self._pack(
                result, language, "knowledge_clarification",
                ["context_intelligence", assessment_mode, "policy_gate:continue", "supervisor_agent", *result["trace"]],
                "specialist_intake_clarification",
                critic={"approved": True, "mode": "curated_intake_template"},
                trace_id=trace_id, context_assessment=assessment,
            )

        budget_exhausted = False
        if self.llm:
            try:
                with stage("supervisor_orchestration", "agent"):
                    fast_agent = self._fast_path_agent(assessment, assessment_mode, decision)
                    if fast_agent:
                        result = self._run_dispatch(fast_agent, routing_message, user_id, session_id, language, history, trace_id, assessment)
                    else:
                        result = self._run_llm(routing_message, user_id, session_id, language, history, trace_id, assessment)
                if selected_topic == "settlement_timing" and topic_agent == "knowledge_specialist" and not result.get("handoff"):
                    # Fixed login prompt (README fixed-text policy: menus/confirmations): the account data needs identity.
                    result["answer"] = result.get("answer", "") + (
                        "\n\nPara ver as datas de recebimento das suas próprias vendas, entre com o login demo."
                        if language == "pt" else "\n\nTo see the settlement dates of your own sales, sign in with the demo login.")
                    result["login_required_for_account_data"] = True
                result["context_assessment"] = self._public_context_assessment(assessment)
                result["trace"] = [*context_trace, *result["trace"]]
                return result
            except LLMTimeout as exc:
                # The contextual safety gate already ran. A deterministic, tool-grounded
                # answer is safe to return and is labelled honestly instead of a 503.
                logger.warning("supervisor_llm_budget_exhausted trace_id=%s error=%s", trace_id, str(exc))
                budget_exhausted = True
            except LLMUnavailable as exc:
                logger.warning("supervisor_llm_unavailable trace_id=%s error=%s", trace_id, str(exc))
                if self.llm_required:
                    raise
        with stage("supervisor_fallback", "agent"):
            result = self._run_fallback(routing_message, user_id, session_id, language, history, trace_id,
                                        budget_exhausted=budget_exhausted)
        result["context_assessment"] = self._public_context_assessment(assessment)
        result["trace"] = [*context_trace, *result["trace"]]
        return result

    def _execute_tool(self, name: str, args: dict, message: str, user_id: str, session_id: str, language: str, history: list[dict], previous: list[dict], trace_id: str) -> dict:
        name = canonical_agent(name)
        component = {
            "knowledge_specialist": "agent",
            "customer_support_specialist": "agent",
            "payments_specialist": "agent",
            "web_research_specialist": "agent",
            "risk_assessment_specialist": "agent",
            "human_escalation_specialist": "agent",
        }.get(name, "tool")
        with stage(name or "unknown_tool", component):
            if name == "knowledge_specialist":
                return self.knowledge.run(str(args.get("query") or message)[:1000], language, history)
            if name == "customer_support_specialist":
                return self.support.run(str(args.get("task") or message)[:1000], user_id, language, history, trace_id)
            if name == "payments_specialist":
                return self.payments.run(str(args.get("task") or message)[:1000], user_id, language, history, trace_id)
            if name == "risk_assessment_specialist":
                return self.risk.assess(str(args.get("issue") or message), history, language)
            if name == "human_escalation_specialist":
                return self.escalation.run(reason=str(args.get("reason", "supervisor_escalation"))[:100], language=language,
                                           user_id=user_id, message=str(args.get("summary") or message)[:1000],
                                           severity=str(args.get("severity", "normal")), session_id=session_id, history=history)
            return {"error": "unknown_tool", "tool": name}

    def _run_fallback(self, message: str, user_id: str, session_id: str, language: str, history: list[dict], trace_id: str,
                      *, budget_exhausted: bool = False) -> dict:
        """Explicit degraded path used when OLLAMA_ENABLED=false/unavailable or the LLM budget ran out."""
        from .router_agent import RouterAgent
        router = RouterAgent()
        route = router.route(message, history)
        trace = ["supervisor_agent", "deterministic_fallback_router"]
        if route == "customer_support":
            started = time.monotonic()
            agent, tool_name = (self.payments, "payments_specialist") if PaymentsAgent.handles(message) else (self.support, "customer_support_specialist")
            result = agent.run(message, user_id, language, history, trace_id)
            self.db.record_tool(trace_id, tool_name, user_id, "ok", int((time.monotonic() - started) * 1000))
            intent = "customer_support"  # route family for Support and Payments; agent is in the trace
        elif route == "general_question":
            started = time.monotonic()
            result = self.knowledge.run(message, language, history)  # web/weather/FX are Knowledge tools
            self.db.record_tool(trace_id, "knowledge_specialist", user_id, "ok" if result.get("confidence", 0) > 0 else "error", int((time.monotonic() - started) * 1000))
            intent = "general_information"
        elif route == "smalltalk":
            result = {"answer": "Hello! I can help with Getnet products, support and public information." if language == "en" else "Olá! Posso ajudar com produtos Getnet, suporte e informações públicas.", "confidence": 0.95, "sources": [], "trace": ["smalltalk"]}
            intent = "smalltalk"
        else:
            started = time.monotonic()
            result = self.knowledge.run(message, language, history)
            self.db.record_tool(trace_id, "knowledge_specialist", user_id, "ok" if result.get("retrieved_chunks", 0) else "error", int((time.monotonic() - started) * 1000))
            intent = "product_information"
            if result.get("confidence", 0) < 0.25:
                result = self.escalation.run(reason="low_knowledge_confidence", language=language, user_id=user_id,
                                             message=message, session_id=session_id, history=history)
                intent = "human_handoff"
        fallback_evidence = self._collect_evidence([result])
        from ..observability import current_timeline
        timeline = current_timeline()
        if timeline is not None and timeline.critic_challenge and not result.get("handoff"):
            from .critic_challenge import corrupt
            result = {**result, "answer": corrupt(result.get("answer", ""), timeline.critic_challenge, language)}
            trace.append(f"critic_challenge_injected:{timeline.critic_challenge}")
        if budget_exhausted:
            review = self.critic.lint(result.get("answer", ""), language,
                                      reason="LLM budget exhausted; deterministic tool-grounded answer, structural checks only.")
            trace.append("llm_budget_exhausted")
        else:
            review = self.critic.review(result.get("answer", ""), language, fallback_evidence,
                                        high_risk=False, user_message=message, conversation_context=history)
        trace.extend(result.get("trace", [])); trace.append("critic_agent")
        blocking = [i for i in review.get("issues") or [] if i == "asks_customer_for_secret" or str(i).startswith("citation_without_source")]
        if blocking and not result.get("handoff"):
            # No model to re-plan with. High-precision deterministic failures (secret request,
            # citation to a missing source) are never shown; the customer gets a hand-off.
            # Heuristic lint issues (e.g. language guess on short text) stay advisory here.
            trace.append("critic_rejected_fallback_handoff")
            result = self.escalation.run(reason="critic_rejected_answer", language=language, user_id=user_id,
                                         message=message, session_id=session_id, history=history)
            trace.extend(result.get("trace", []))
            intent = "human_handoff"
        mode = "deterministic_fallback_llm_budget" if budget_exhausted else "deterministic_fallback"
        result = {**result, "degraded": True,
                  "degraded_reason": "llm_budget_exhausted" if budget_exhausted else ("llm_disabled" if not self.llm else (result.get("degraded_reason") or "llm_unavailable"))}
        return self._pack(result, language, intent, trace, mode, critic=review, trace_id=trace_id, tool_calls=0)

