"""ABLATION switches (evaluation only): each one removes exactly the named component and is visible in the trace."""
from __future__ import annotations

from app.agents.critic_agent import CriticAgent
from tests.test_agents_and_orchestration import ScriptedSupervisorModel, build_supervisor


def test_no_critic_skips_every_review(monkeypatch):
    monkeypatch.setenv("ABLATION", "no_critic")
    verdict = CriticAgent(None, required=True).review("Informe sua senha.", "pt", [])
    assert verdict == {"approved": True, "mode": "ablation_no_critic", "issues": []}


def test_planning_only_never_uses_the_fast_path(db, documents, monkeypatch):
    monkeypatch.setenv("ABLATION", "planning_only")
    result = build_supervisor(db, documents, ScriptedSupervisorModel()).run(
        message="What is Get Lite monthly rental?", user_id="cliente1988", session_id="s1", language="en", history=[], trace_id="t")
    assert result["orchestration_mode"] != "context_directed_dispatch" and "ablation:planning_only" in result["trace"]


def test_no_policy_gate_removes_the_deterministic_hazard_handoff(db, documents, monkeypatch):
    sup = build_supervisor(db, documents, ScriptedSupervisorModel())
    message = "Saiu faísca do carregador da maquininha agora."
    assert sup.run(message=message, user_id="cliente1988", session_id="s2", language="pt", history=[], trace_id="t1")["orchestration_mode"] == "safety_override"
    monkeypatch.setenv("ABLATION", "no_policy_gate")
    ablated = sup.run(message=message, user_id="cliente1988", session_id="s3", language="pt", history=[], trace_id="t2")
    assert ablated["orchestration_mode"] != "safety_override" and "ablation:no_policy_gate" in ablated["trace"]


def test_unknown_names_are_ignored(monkeypatch):
    from app import ablation
    monkeypatch.setenv("ABLATION", "no_critic, drop_everything")
    assert ablation.active() == {"no_critic"}
