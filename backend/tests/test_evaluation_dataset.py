import json
from pathlib import Path

from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.router_agent import RouterAgent


def test_official_challenge_scenario_routes_and_rag_retrieval(documents):
    cases = json.loads((Path(__file__).parents[1] / "app" / "evaluation" / "scenarios.json").read_text(encoding="utf-8"))
    router = RouterAgent()
    knowledge = KnowledgeAgent(documents)
    assert len(cases) == 10
    for case in cases:
        assert router.route(case["message"]) == case["expected_route"], case["id"]
        if case.get("required_evidence"):
            matches = knowledge.retrieve(case["message"], k=5, language=case["language"])
            assert any(case["required_evidence"].lower() in item["title"].lower() for item in matches), case["id"]
