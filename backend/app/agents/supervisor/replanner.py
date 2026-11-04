"""The single re-plan after a Critic rejection (one specialist call or a corrected draft)."""
from __future__ import annotations

import logging

import json
import os
import time

from .constants import FINAL_MARKER, SUPERVISOR_TOOLS, canonical_agent

logger = logging.getLogger("app.agents.supervisor_agent")

class ReplanMixin:
    def _replan_after_rejection(self, message: str, language: str, history: list[dict], specialist_results: list[dict],
                                critic_result: dict, user_id: str, session_id: str, trace_id: str,
                                trace: list[str]) -> tuple[str, list[dict], int] | None:
        """One bounded re-plan: the Supervisor sees the Critic issues and either calls one
        specialist for missing evidence or rewrites the answer from the observations."""
        issues = "; ".join(str(i) for i in critic_result.get("issues") or [])[:400] or "unsupported or inconsistent answer"
        observations = []
        for result in specialist_results:
            item = json.loads(self._observation_for_model(result))
            data = [compact for compact in (result.get("tool_observations") or [])]
            if data:
                from ..specialist import compact_observation
                item["tool_data"] = [compact_observation(o) for o in data]
            if result.get("tool_result"):
                item["tool_result"] = result["tool_result"]
            observations.append(item)
        language_rule = "English only" if language == "en" else "Brazilian Portuguese only"
        messages = [
            {"role": "system", "content": (
                "You are the Supervisor Agent. An independent critic rejected the draft answer. Either call ONE specialist tool "
                "to obtain the missing evidence, or write a corrected short answer using only values present in the observations. "
                "Copy values exactly as they appear in the observations. Never add numbers, dates or identifiers that are not in the observations. "
                "Write only the customer-facing answer: never mention the critic, the draft, tools, observations or any internal process. "
                f"Respond in {language_rule}.")},
            {"role": "user", "content": f"Request: {message[:600]}"},
            {"role": "user", "content": "Observations: " + json.dumps(observations, ensure_ascii=False, default=str)[:self.TOOL_CONTENT_CHARS]},
            {"role": "user", "content": f"Critic issues: {issues}"},
        ]
        response = self.llm.chat(messages, SUPERVISOR_TOOLS, max_tokens=int(os.getenv("OLLAMA_SUPERVISOR_MAX_OUTPUT_TOKENS", "200")),
                                 purpose="supervisor_replan")
        trace.append("supervisor_replan")
        assistant = response.get("message", {}) or {}
        calls = assistant.get("tool_calls") or []
        if calls:
            function = calls[0].get("function", {})
            name = canonical_agent(str(function.get("name") or ""))
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try: args = json.loads(args)
                except json.JSONDecodeError: args = {}
            started = time.monotonic()
            result = self._execute_tool(name, args if isinstance(args, dict) else {}, message, user_id, session_id,
                                        language, history, specialist_results, trace_id)
            self.db.record_tool(trace_id, name or "unknown", user_id, "ok" if not result.get("error") else "error",
                                int((time.monotonic() - started) * 1000))
            trace.append(f"replan_tool:{name}")
            if result.get("error") or not result.get("answer"):
                return None
            return str(result["answer"]).strip(), [*specialist_results, result], 1
        content = str(assistant.get("content", "")).strip()
        if not content or content.upper().startswith(FINAL_MARKER):
            return None
        return content, specialist_results, 0

