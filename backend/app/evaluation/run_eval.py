from __future__ import annotations

import json
from pathlib import Path

from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.router_agent import RouterAgent
from app.knowledge.ingest import load_documents


def main() -> int:
    dataset = json.loads((Path(__file__).parent / "scenarios.json").read_text(encoding="utf-8"))
    docs = load_documents()
    knowledge = KnowledgeAgent(docs)
    router = RouterAgent()
    route_hits = 0; retrieval_hits = 0; retrieval_total = 0
    results = []
    for case in dataset:
        actual_route = router.route(case["message"])
        route_ok = actual_route == case["expected_route"]
        route_hits += int(route_ok)
        retrieval_ok = None
        if case.get("required_evidence"):
            retrieval_total += 1
            query = case["message"]
            matches = knowledge.retrieve(query, k=5, language=case["language"])
            retrieval_ok = any(case["required_evidence"].lower() in item["title"].lower() for item in matches)
            retrieval_hits += int(retrieval_ok)
        results.append({"id": case["id"], "route_expected": case["expected_route"], "route_actual": actual_route,
                        "route_pass": route_ok, "retrieval_pass": retrieval_ok})
    report = {"dataset_size": len(dataset), "route_accuracy": route_hits / len(dataset),
              "retrieval_recall_at_5": retrieval_hits / retrieval_total if retrieval_total else None,
              "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if route_hits == len(dataset) and retrieval_hits == retrieval_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
