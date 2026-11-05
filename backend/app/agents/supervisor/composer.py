"""Abstention, Critic review, re-plan/handoff decision and response packing."""
from __future__ import annotations

import logging
import re

from ...infra.llm import LLMTimeout
from ..clarification import clarification_result

logger = logging.getLogger("app.agents.supervisor_agent")

CITATION = re.compile(r"\[\d{1,2}\]")


class ComposerMixin:
    def _finalize(self, specialist_results: list[dict], draft: str, trace: list[str], message: str, user_id: str,
                  session_id: str, language: str, history: list[dict], trace_id: str, *, mode: str,
                  tool_calls: int, context_assessment: dict, replanned: bool = False) -> dict:
        """Abstain, review once with the Critic, then answer or escalate."""
        model_written = bool(draft)
        sources: list[dict] = []
        for result in specialist_results:
            for source in result.get("sources", []):
                if source not in sources: sources.append(source)
        knowledge_results = [
            item for item in specialist_results
            if item.get("trace", [""])[0] == "knowledge_agent"
        ]
        if (
            knowledge_results
            and len(knowledge_results) == len(specialist_results)
            and all(not item.get("evidence") for item in knowledge_results)
        ):
            result = clarification_result(language, unsupported=True)
            return self._pack(
                result, language, "knowledge_scope_clarification",
                trace + ["knowledge_evidence_missing", "topic_options_presented"],
                "grounded_knowledge_abstention",
                critic={"approved": True, "mode": "evidence_policy"},
                trace_id=trace_id, tool_calls=tool_calls, context_assessment=context_assessment,
            )

        cited = [r for r in specialist_results if CITATION.search(str(r.get("answer", "")))]
        if draft and cited and not CITATION.search(draft):
            # The planner rewrote cited specialist answers and dropped their [n] markers: the
            # specialists' own answers (with citations) are used instead.
            draft, model_written = "", False
            trace = trace + ["planner_draft_dropped_citations_replaced"]
        if not draft:
            # The specialists' own answers are the draft; no extra generation needed.
            answers = list(dict.fromkeys(str(r.get("answer", "")).strip() for r in specialist_results if r.get("answer")))
            draft = "\n\n".join(answers)
        if not draft:
            draft = ("Não consegui concluir a análise com segurança. Vou encaminhar para atendimento." if language == "pt" else "I could not complete the analysis safely. I will create a support hand-off.")
        from ...observability import current_timeline
        timeline = current_timeline()
        if timeline is not None and timeline.critic_challenge and not replanned:
            from ..critic_challenge import corrupt
            draft = corrupt(draft, timeline.critic_challenge, language)
            trace = trace + [f"critic_challenge_injected:{timeline.critic_challenge}"]

        # Code-enforced, single critic pass over the exact text that will be returned.
        proposals = [r["pending_action"] for r in specialist_results if r.get("pending_action")]
        if not model_written and any(r.get("handoff") for r in specialist_results):
            # Hand-off confirmations are deterministic templates, not generated claims.
            critic_result = {"approved": True, "mode": "handoff_policy", "issues": []}
        elif not model_written and proposals and len(specialist_results) == 1:
            # Confirmation menu built from the validated record: every ID/value/date it states must be in that record.
            from ..grounding import find_unsupported
            unsupported = find_unsupported(draft, proposals)
            critic_result = {"approved": not unsupported, "mode": "action_confirmation_check",
                             "issues": [f"not_in_action_record:{u}" for u in unsupported[:3]]}
        else:
            evidence = self._collect_evidence(specialist_results)
            critic_result = self.critic.review(draft, language, evidence, user_message=message, conversation_context=history,
                                               grounding_observations=self._grounding_observations(specialist_results))
            if critic_result.get("mode") == "llm_critic_timeout":
                raise LLMTimeout("LLM budget exhausted during critic review")
        trace.append("critic_agent_final_review")
        if not critic_result.get("approved") and self.llm is not None and not replanned:
            trace.append("critic_rejected")
            revised = self._replan_after_rejection(message, language, history, specialist_results, critic_result,
                                                   user_id, session_id, trace_id, trace)
            if revised is not None:
                draft, specialist_results, extra_calls = revised
                tool_calls += extra_calls
                sources = [s for r in specialist_results for s in r.get("sources", [])]
                sources = [s for i, s in enumerate(sources) if s not in sources[:i]]
                critic_result = self.critic.review(draft, language, self._collect_evidence(specialist_results),
                                                   user_message=message, conversation_context=history,
                                                   grounding_observations=self._grounding_observations(specialist_results))
                if critic_result.get("mode") == "llm_critic_timeout":
                    raise LLMTimeout("LLM budget exhausted during critic re-check")
                trace.append("critic_recheck")
        if not critic_result.get("approved"):
            handoff = self.escalation.run(reason="critic_rejected", language=language, user_id=user_id,
                                          message=message, session_id=session_id, history=history)
            return self._pack(handoff, language, "quality_escalation", trace + handoff["trace"], mode, critic=critic_result,
                              trace_id=trace_id, sources=sources, tool_calls=tool_calls)
        degraded = [r for r in specialist_results if r.get("degraded")]
        combined = {
            "answer": draft,
            "degraded": bool(degraded),
            "degraded_reason": degraded[0].get("degraded_reason") if degraded else None,
            "confidence": min(0.97, max([r.get("confidence", 0.65) for r in specialist_results] or [0.65])),
            "sources": sources,
            "handoff": any(r.get("handoff", False) for r in specialist_results),
            "retrieved_chunks": sum(r.get("retrieved_chunks", 0) for r in specialist_results),
            "specialist_results": specialist_results,
        }
        for result in specialist_results:
            for key in ("handoff_protocol", "handoff_status", "handoff_severity", "real_agent_connected", "handoff_reason", "risk_level", "pending_action"):
                if key in result: combined[key] = result[key]
        intent = self._intent_from_results(specialist_results)
        return self._pack(combined, language, intent, trace + ["supervisor_final"], mode, critic=critic_result, trace_id=trace_id, tool_calls=tool_calls)

    @staticmethod
    def _grounding_observations(results: list[dict]) -> list:
        """Structured data a generated answer may quote (None when there is none)."""
        structured = [r for r in results if r.get("tool_observations") or r.get("tool_result")]
        if not structured:
            return []
        facts: list = []
        for result in results:
            facts.extend(result.get("tool_observations") or [])
            if result.get("tool_result"):
                facts.append(result["tool_result"])
            facts.extend(result.get("evidence") or [])
        return facts

    @staticmethod
    def _collect_evidence(results: list[dict]) -> list[dict]:
        """At most 8 items, shared fairly between specialists (round-robin), each specialist's
        structured tool data first. Taking the first 8 in call order let a Knowledge answer
        (4 passages + sources) push the Payments records out, and the Critic then rejected
        correct amounts as "not in the evidence" (benchmark 2026-11-04, multi-intent)."""
        queues: list[list[dict]] = []
        for item in results:
            queue = list(item.get("tool_observations", []))
            if item.get("tool_result"):
                queue.append(item["tool_result"])
            queue.extend(item.get("evidence", []))
            queue.extend({"source_title": s.get("title"), "source_url": s.get("url")} for s in item.get("sources", []))
            if queue:
                queues.append(queue)
        evidence: list[dict] = []
        while len(evidence) < 8 and any(queues):
            for queue in queues:
                if queue and len(evidence) < 8:
                    evidence.append(queue.pop(0))
        return evidence

    @staticmethod
    def _public_context_assessment(assessment: dict) -> dict:
        return {key: value for key, value in assessment.items() if key != "rationale"}

    @staticmethod
    def _intent_from_results(results: list[dict]) -> str:
        tools = {str(item.get("trace", [""])[0]) for item in results}
        if any(item.get("handoff") for item in results): return "human_handoff"
        if any(item.get("retrieved_chunks") for item in results): return "product_information"
        if any(item.get("tool_result", {}).get("tool") in {"open_meteo_weather", "frankfurter_exchange_rates", "duckduckgo_public_search"} for item in results): return "general_information"
        if any(item.get("tool_observations") for item in results): return "customer_support"
        return "multi_agent_assistance"

    @staticmethod
    def _pack(result: dict, language: str, intent: str, trace: list[str], mode: str, *, critic: dict, trace_id: str, sources: list[dict] | None = None, tool_calls: int = 0, context_assessment: dict | None = None) -> dict:
        payload = {
            "answer": result.get("answer", ""), "language": language, "intent": intent,
            "agent": result.get("agent", "supervisor_agent"), "confidence": result.get("confidence", 0.5),
            "sources": sources if sources is not None else result.get("sources", []),
            "handoff": result.get("handoff", False), "trace": trace,
            "retrieved_chunks": result.get("retrieved_chunks", 0), "trace_id": trace_id,
            "orchestration_mode": mode, "critic": critic, "tool_calls": tool_calls,
        }
        payload["degraded"] = bool(result.get("degraded", False))
        payload["degraded_reason"] = result.get("degraded_reason") if payload["degraded"] else None
        for key in ("handoff_reason", "handoff_protocol", "handoff_status", "handoff_severity", "real_agent_connected", "risk_level", "retrieval_mode", "clarification_kind", "pending_action"):
            if key in result: payload[key] = result[key]
        if "clarification_options" in result:
            payload["clarification_options"] = result["clarification_options"]
        if "clarification_topic" in result:
            payload["clarification_topic"] = result["clarification_topic"]
        if context_assessment is not None:
            # Keep structured routing signals, but never expose the model's rationale.
            payload["context_assessment"] = {
                key: value for key, value in context_assessment.items() if key != "rationale"
            }
        observations = result.get("specialist_results") or result.get("tool_observations")
        if observations is not None: payload["specialist_observations"] = observations
        return payload
