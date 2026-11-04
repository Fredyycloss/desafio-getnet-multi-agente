from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from app.infra.database import Database
from app.infra.llm import create_llm
from app.knowledge.ingest import load_documents
from app.service import ChatService
from app.language import detect_language


def normalize_intent(intent: str) -> str:
    if intent in {"product_information", "knowledge"}:
        return "knowledge"
    if intent in {"customer_support"}:
        return "customer_support"
    if intent in {"general_information", "general_question"}:
        return "general_question"
    return intent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the challenge evaluation dataset through the live Ollama supervisor.")
    parser.add_argument("--output", default="live-evaluation-report.json")
    parser.add_argument("--user-id", default="cliente1988")
    args = parser.parse_args()
    model = create_llm()
    if model is None:
        raise SystemExit("No LLM provider configured: set GETNET_ANTHROPIC_API_KEY or OLLAMA_ENABLED=true.")
    health = model.health()
    if not health.get("available") or not health.get("chat_model_loaded"):
        raise SystemExit(f"Configured chat model is not available: {health}")

    dataset_path = Path(__file__).parent / "scenarios.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    docs = load_documents()
    with tempfile.TemporaryDirectory(prefix="getnet-live-eval-") as temp_dir:
        db = Database(str(Path(temp_dir) / "evaluation.sqlite3"))
        service = ChatService(docs, db, model)
        cases = []
        for scenario in dataset:
            session_id = f"live-eval-{scenario['id']}-{uuid4().hex[:8]}"
            response = service.answer(
                scenario["message"], args.user_id, session_id, history=[], trace_id=uuid4().hex
            )
            route = normalize_intent(response.get("intent", "unknown"))
            source_urls = [item.get("url", "") for item in response.get("sources", [])]
            source_hit = any(f in url for url in source_urls for f in scenario.get("expected_urls", []))
            answer_language = detect_language(response.get("answer", ""))
            case = {
                "id": scenario["id"],
                "expected_route": scenario["expected_route"],
                "actual_route": route,
                "route_pass": route == scenario["expected_route"],
                "expected_language": scenario["language"],
                "actual_language": response.get("language"),
                "answer_language_detected": answer_language,
                "language_pass": response.get("language") == scenario["language"] and answer_language == scenario["language"],
                "expected_source": scenario.get("expected_urls"),
                "source_hit": source_hit if scenario.get("expected_urls") else None,
                "orchestration_mode": response.get("orchestration_mode"),
                "tool_calls": response.get("tool_calls", 0),
                "critic": response.get("critic"),
                "handoff": response.get("handoff", False),
                "trace_id": response.get("trace_id"),
                "trace": response.get("trace", []),
                "answer": response.get("answer", ""),
                "sources": response.get("sources", []),
            }
            cases.append(case)
            print(f"[{scenario['id']}] route={case['route_pass']} language={case['language_pass']} tools={case['tool_calls']} critic={case['critic']}")
        db.close()

    route_accuracy = sum(item["route_pass"] for item in cases) / max(len(cases), 1)
    language_accuracy = sum(item["language_pass"] for item in cases) / max(len(cases), 1)
    retrieval_items = [item for item in cases if item["expected_source"]]
    retrieval_recall = sum(bool(item["source_hit"]) for item in retrieval_items) / max(len(retrieval_items), 1)
    report = {
        "dataset_size": len(cases),
        "mode": "live_llm_supervisor",
        "model": model.model,
        "embedding_model": model.embedding_model,
        "route_accuracy": round(route_accuracy, 4),
        "language_accuracy": round(language_accuracy, 4),
        "retrieval_recall_at_5": round(retrieval_recall, 4),
        "all_critic_approved": all(bool(item.get("critic", {}).get("approved")) for item in cases),
        "cases": cases,
    }
    target = Path(args.output)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2))
    print(f"Full report saved to {target.resolve()}")
    return 0 if route_accuracy == 1 and language_accuracy == 1 and retrieval_recall == 1 and report["all_critic_approved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
