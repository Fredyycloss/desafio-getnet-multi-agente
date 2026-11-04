"""Single-specialist dispatch when the Context Intelligence is confident (no planning call)."""
from __future__ import annotations

import logging

import json
import os
import time

from ..context_intelligence import CONTEXT_MODES
from .constants import FAST_PATH_AGENTS, canonical_agent

logger = logging.getLogger("app.agents.supervisor_agent")

class FastPathMixin:
    def _fast_path_agent(self, assessment: dict, assessment_mode: str, decision: dict) -> str | None:
        """Return the single routine specialist to dispatch directly, if any."""
        from ... import ablation
        if ablation.on("planning_only") or assessment_mode not in CONTEXT_MODES or decision.get("action") != "continue":
            return None
        agents = list(dict.fromkeys(canonical_agent(a) for a in assessment.get("recommended_agents") or []))
        if ablation.on("fast_path_only"):
            routine = [a for a in agents if a in FAST_PATH_AGENTS]
            return routine[0] if routine else None
        if len(agents) != 1 or agents[0] not in FAST_PATH_AGENTS:
            return None
        try:
            threshold = float(os.getenv("SUPERVISOR_FAST_PATH_MIN_CONFIDENCE", "0.75"))
        except ValueError:
            threshold = 0.75
        if float(assessment.get("confidence", 0)) < threshold:
            return None
        return agents[0]

    def _run_dispatch(self, name: str, message: str, user_id: str, session_id: str, language: str,
                      history: list[dict], trace_id: str, context_assessment: dict) -> dict:
        """Context-directed dispatch: no planning generation for a clear single-specialist turn."""
        trace = ["supervisor_agent", "context_directed_dispatch"]
        started = time.monotonic()
        result = self._execute_tool(name, {}, message, user_id, session_id, language, history, [], trace_id)
        self.db.record_tool(trace_id, name, user_id, "ok" if not result.get("error") else "error",
                            int((time.monotonic() - started) * 1000))
        trace.append(f"tool:{name}")
        return self._finalize(
            [result], "", trace, message, user_id, session_id, language, history, trace_id,
            mode="context_directed_dispatch", tool_calls=1, context_assessment=context_assessment,
        )

    @staticmethod
    def _observation_for_model(result: dict) -> str:
        """Compact specialist observation for the planner (no raw evidence dumps)."""
        keep = {key: result[key] for key in (
            "answer", "confidence", "handoff", "handoff_protocol", "risk_level", "error", "retrieved_chunks",
        ) if key in result}
        if result.get("sources"):
            keep["sources"] = [s.get("title") for s in result["sources"][:4]]
        return json.dumps(keep, ensure_ascii=False, default=str)

