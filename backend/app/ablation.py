"""Ablation switches for the V7-G study (evaluation only, never set in compose files).

ABLATION is a comma list of:
  no_critic                -> no Critic review at all (deterministic checks included)
  no_context_intelligence  -> no contextual model pass; the Supervisor plans alone (no fast path)
  no_policy_gate           -> no deterministic RiskAssessment / PolicyGate (safety set only)
  fast_path_only           -> dispatch to the first recommended specialist whenever there is one
  planning_only            -> never use the fast path
Every response made under an ablation carries "ablation:<names>" in its trace.
"""
from __future__ import annotations

import os

KNOWN = {"no_critic", "no_context_intelligence", "no_policy_gate", "fast_path_only", "planning_only"}


def active() -> set[str]:
    return {x.strip() for x in os.getenv("ABLATION", "").split(",") if x.strip()} & KNOWN


def on(name: str) -> bool:
    return name in active()
