"""Common contract and tool-using base for specialist agents.

Every specialist returns ``specialist_result(...)``:
``{agent, task, answer, evidence[], tool_calls[{tool,args,ok,duration_ms}], sources[],
confidence, missing_info[], degraded, degraded_reason, duration_ms, trace}`` plus
agent-specific keys kept for compatibility (``tool_observations``, ``tool_result``...).

``degraded`` is True whenever the answer did not come from the normal model path
(model disabled/unavailable/out of budget, model chose no tool, template text).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from uuid import uuid4

from ..infra.database import Database
from ..infra.llm import LLMAuthError, LLMBudgetExceeded, LLMProvider, LLMTimeout, LLMUnavailable
from ..observability import stage


def specialist_result(*, agent: str, task: str, answer: str, confidence: float, started: float,
                      evidence: list | None = None, tool_calls: list[dict] | None = None,
                      sources: list[dict] | None = None, missing_info: list[str] | None = None,
                      degraded: bool = False, degraded_reason: str | None = None,
                      trace: list[str] | None = None, **extra: Any) -> dict:
    result = {
        "agent": agent,
        "task": task[:300],
        "answer": answer,
        "evidence": evidence or [],
        "tool_calls": tool_calls or [],
        "sources": sources or [],
        "confidence": confidence,
        "missing_info": missing_info or [],
        "degraded": degraded,
        "degraded_reason": degraded_reason if degraded else None,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "trace": trace or [agent],
    }
    result.update(extra)
    return result


def degraded_reason_for(exc: BaseException | None, llm_present: bool) -> str:
    if not llm_present:
        return "llm_disabled"
    if isinstance(exc, LLMAuthError):
        return exc.reason
    if isinstance(exc, LLMBudgetExceeded):
        return "llm_budget_exhausted"
    if isinstance(exc, LLMTimeout):
        return "llm_timeout"
    return "llm_unavailable"


def parse_tool_calls(response: dict, limit: int = 4) -> list[tuple[str, dict]]:
    calls = (response.get("message") or {}).get("tool_calls") or []
    parsed: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for call in calls[:limit]:
        function = call.get("function", {})
        name = str(function.get("name") or "")
        args = function.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        args = args if isinstance(args, dict) else {}
        key = name + json.dumps(args, sort_keys=True)
        if key not in seen:
            seen.add(key)
            parsed.append((name, args))
    return parsed


class ToolSpecialist:
    """The model selects typed tools, code executes them, the model writes the answer.

    Tool arguments never include ``user_id``: closures bind the server-side id.
    Subclasses define the tool set, prompts, the keyword fallback selection and
    the template fallback; both fallbacks mark the result as degraded.
    """
    name = "tool_specialist"
    tool_schemas: list[dict] = []
    selection_prompt = ""
    writer_role = ""
    answer_tokens_env = "OLLAMA_SUPPORT_ANSWER_MAX_OUTPUT_TOKENS"
    # Write actions this specialist may PROPOSE (app/actions/catalog.py). Never executed here.
    action_kinds: tuple[str, ...] = ()
    action_prompt = ""

    def __init__(self, db: Database, llm: LLMProvider | None = None, actions=None):
        self.db = db
        self.llm = llm
        self.actions = actions

    def _schemas(self) -> list[dict]:
        if not self.actions:
            return self.tool_schemas
        from ..actions.catalog import KINDS
        return self.tool_schemas + [KINDS[k].tool for k in self.action_kinds]

    def _action_tools(self, user_id: str, language: str) -> dict[str, Callable[[dict], dict]]:
        if not self.actions:
            return {}
        from ..actions.catalog import KINDS
        from ..observability import current_timeline
        timeline = current_timeline()
        session_id = timeline.session_id if timeline else None
        return {KINDS[k].tool["function"]["name"]: (lambda args, k=k: self.actions.propose(user_id, session_id, k, args, language))
                for k in self.action_kinds}

    # -- subclass hooks -------------------------------------------------------
    def bind_tools(self, user_id: str) -> dict[str, Callable[[dict], dict]]:
        raise NotImplementedError

    def keyword_selection(self, task: str) -> list[tuple[str, dict]]:
        raise NotImplementedError

    def compose_template(self, observations: list[dict], language: str) -> str:
        raise NotImplementedError

    # -- shared flow ------------------------------------------------------------
    def run(self, task: str, user_id: str, language: str = "pt", history: list[dict] | None = None,
            trace_id: str | None = None) -> dict:
        started = time.monotonic()
        audit_trace = trace_id or uuid4().hex
        raw_tools = {**self.bind_tools(user_id), **self._action_tools(user_id, language)}
        tool_calls: list[dict] = []
        observations: list[dict] = []
        trace: list[str] = [self.name]

        def invoke(name: str, args: dict) -> None:
            t0 = time.monotonic()
            status = "error"
            try:
                with stage(f"{self.name}_tool:{name}", "tool"):
                    result = raw_tools[name](args) if name in raw_tools else {"ok": False, "error": "unknown_tool", "tool": name}
                status = "ok" if result.get("ok") else "error"
            finally:
                duration = int((time.monotonic() - t0) * 1000)
                self.db.record_tool(audit_trace, name or "unknown", user_id, status, duration)
            observations.append(result)
            tool_calls.append({"tool": name, "args": args, "ok": status == "ok", "duration_ms": duration})
            trace.append(f"tool:{name}")

        degraded_reason: str | None = None
        answer: str | None = None
        with stage(self.name, "agent"):
            if self.llm:
                try:
                    selected = self._select_with_model(task, history or [])
                    trace.insert(1, "llm_tool_selection")
                    if not selected:
                        degraded_reason = "model_selected_no_tool"
                        trace.append("model_selected_no_tool")
                        selected = self.keyword_selection(task)
                        trace.append("keyword_tool_selection_fallback")
                    for name, args in selected:
                        invoke(name, args)
                    proposal = next((o for o in observations if o.get("ok") and (o.get("pending_action") or o.get("already_executed"))), None)
                    if proposal:
                        # The model chose the action and its arguments; the confirmation menu is fixed text
                        # built from the validated record (README fixed-text policy, item c).
                        answer = proposal.get("confirmation_text") or self.actions.result_text(
                            {"outcome": "already_executed", "action": proposal["action"], "protocol": proposal["protocol"]}, language)
                        trace.append("action_proposed_awaiting_confirmation" if proposal.get("pending_action") else "action_already_executed")
                    else:
                        answer = self._write_with_model(task, language, observations)
                    if answer and not proposal:
                        trace.append("llm_answer_from_tool_observations")
                except LLMUnavailable as exc:
                    degraded_reason = degraded_reason_for(exc, True)
                    if not observations:
                        for name, args in self.keyword_selection(task):
                            invoke(name, args)
                        trace.append("keyword_tool_selection_fallback")
            else:
                degraded_reason = "llm_disabled"
                for name, args in self.keyword_selection(task):
                    invoke(name, args)
                trace.append("keyword_tool_selection_fallback")
            if not answer:
                degraded_reason = degraded_reason or "llm_empty_answer"
                answer = self.compose_template(observations, language)
                trace.append("template_fallback")

        good = any(o.get("ok") for o in observations)
        pending = next((o["pending_action"] for o in observations if o.get("ok") and o.get("pending_action")), None)
        extra = {"pending_action": pending} if pending else {}
        return specialist_result(
            agent=self.name, task=task, answer=answer, confidence=0.9 if good else 0.35, started=started,
            evidence=[o for o in observations if o.get("ok")], tool_calls=tool_calls,
            missing_info=[str(o.get("error")) for o in observations if not o.get("ok")],
            degraded=degraded_reason is not None, degraded_reason=degraded_reason, trace=trace,
            tool_observations=observations,
            agent_mode="llm_tool_selection_and_answer" if degraded_reason is None else "degraded_" + degraded_reason,
            **extra,
        )

    def _select_with_model(self, task: str, history: list[dict]) -> list[tuple[str, dict]]:
        messages: list[dict] = [{"role": "system", "content": self.selection_prompt + (" " + self.action_prompt if self.actions and self.action_prompt else "")}]
        for item in history[-4:]:
            if item.get("role") in {"user", "assistant"}:
                messages.append({"role": item["role"], "content": str(item.get("content", ""))[:300]})
        messages.append({"role": "user", "content": f"Task: {task[:600]}"})
        response = self.llm.chat(messages, self._schemas(),
                                 max_tokens=int(os.getenv("OLLAMA_SUPPORT_MAX_OUTPUT_TOKENS", "80")),
                                 purpose=f"{self.name}:tool_selection")
        allowed = {schema["function"]["name"] for schema in self._schemas()}
        return [(name, args) for name, args in parse_tool_calls(response) if name in allowed]

    def _write_with_model(self, task: str, language: str, observations: list[dict]) -> str | None:
        system = (
            f"{self.writer_role} Answer the customer's request using ONLY the tool observations JSON. "
            "Copy identifiers, amounts, dates and statuses exactly as they appear; never invent or recompute values. "
            "If an observation is missing or failed, say so. State that the records are synthetic demo data, not real Getnet accounts. "
            "You may suggest basic low-risk checks for the observed problem, but no specific procedures, codes, phone numbers or promises. "
            "Be concise (at most 5 sentences). "
            + ("Respond only in English." if language == "en" else "Responda somente em português brasileiro.")
        )
        payload = {"request": task[:600], "observations": [compact_observation(o) for o in observations]}
        response = self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            think=False, temperature=0.0, max_tokens=int(os.getenv(self.answer_tokens_env, "180")),
            purpose=f"{self.name}:answer",
        )
        content = str((response.get("message") or {}).get("content", "")).strip()
        return content or None


def compact_observation(observation: dict) -> dict:
    """Only the fields a customer answer needs; keeps the prompt short. Never includes user_id."""
    keep_tx = ("transaction_id", "amount", "net_amount", "payment_method", "transaction_status",
               "settlement_date", "settlement_status", "error_code", "description")
    compact = {key: observation[key] for key in (
        "tool", "ok", "error", "message", "transaction_date", "approved_count", "net_total_brl", "settlement_dates",
    ) if key in observation}
    if "transactions" in observation:
        compact["transactions"] = [{k: tx.get(k) for k in keep_tx if tx.get(k) is not None}
                                   for tx in observation["transactions"][:10]]
    if isinstance(observation.get("data"), dict):
        compact["data"] = {k: v for k, v in observation["data"].items() if v is not None and k != "user_id"}
    return compact
