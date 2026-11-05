"""Retrieval evaluation: recall@1/3/5, MRR and correct abstention.

    python -m app.evaluation.run_retrieval_eval [--output docs/eval/RETRIEVAL_EVAL_<date>.json]

Compares the legacy 26 hand-written summaries with the full-site snapshot, and BM25 vs
dense vs hybrid on the snapshot. Labels live in retrieval_questions.json (expected official
URL fragments and, when meaningful, words expected in the section heading); questions with
no expected URL are out of the knowledge base and should be abstained on.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from datetime import date
from pathlib import Path

from app.agents.knowledge_agent import MIN_RELEVANCE, KnowledgeAgent, relevant
from app.knowledge.ingest import latest_snapshot, load_documents, load_legacy_curated, load_snapshot_vectors

QUESTIONS = Path(__file__).with_name("retrieval_questions.json")


def evaluate(agent: KnowledgeAgent, questions: list[dict], mode: str) -> dict:
    rows, latencies = [], []
    for q in questions:
        t0 = time.perf_counter()
        hits = agent.retrieve(q["question"], k=5, language=q["language"], mode=mode)
        latencies.append((time.perf_counter() - t0) * 1000)
        urls = [h["url"] for h in hits]
        expected = q.get("expected_urls") or []
        rank = next((i + 1 for i, h in enumerate(hits) if any(frag in h["url"] for frag in expected)), None) if expected else None
        section_ok = None
        if expected and q.get("expected_section_terms") and rank:
            section = (hits[rank - 1].get("section") or "").casefold()
            section_ok = any(term.casefold() in section for term in q["expected_section_terms"])
        top = hits[0]["relevance"] if hits else 0.0
        answered = bool(hits) and relevant(hits[0], q["language"])
        answerable = bool(expected)
        rows.append({"id": q["id"], "answerable": answerable, "rank": rank, "top_relevance": top,
                     "abstain_correct": (not answered) if not answerable else None,
                     "answered_when_answerable": answered if answerable else None,
                     "section_hit": section_ok, "top_urls": urls[:3]})
    ans = [r for r in rows if r["answerable"]]
    oob = [r for r in rows if not r["answerable"]]
    recall = lambda k: round(sum(1 for r in ans if r["rank"] and r["rank"] <= k) / max(len(ans), 1), 4)  # noqa: E731
    sections = [r["section_hit"] for r in ans if r["section_hit"] is not None]
    return {
        "mode": mode, "answerable": len(ans), "out_of_base": len(oob),
        "recall@1": recall(1), "recall@3": recall(3), "recall@5": recall(5),
        "mrr": round(sum(1 / r["rank"] for r in ans if r["rank"]) / max(len(ans), 1), 4),
        "section_hit_rate_when_url_found": round(sum(sections) / len(sections), 4) if sections else None,
        "abstention_accuracy_out_of_base": round(sum(1 for r in oob if r["abstain_correct"]) / max(len(oob), 1), 4),
        "answer_rate_in_base": round(sum(1 for r in ans if r["answered_when_answerable"]) / max(len(ans), 1), 4),
        "mean_latency_ms": round(statistics.mean(latencies), 2), "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-dense", action="store_true", help="skip modes that need the embedding model")
    parser.add_argument("--dataset", default=str(QUESTIONS),
                         help="path to a questions .json file (default: retrieval_questions.json, the dev split); "
                              "pass retrieval_questions_test.json or retrieval_test_v2.json for the frozen splits")
    args = parser.parse_args()
    questions = json.loads(Path(args.dataset).read_text(encoding="utf-8"))["questions"]
    llm = None
    if not args.no_dense:
        from app.infra.llm.ollama import OllamaProvider
        llm = OllamaProvider()
    snapshot = latest_snapshot()
    model, _, vectors = load_snapshot_vectors(snapshot)
    new_agent = KnowledgeAgent(load_documents(), llm=llm, vectors=vectors, vector_model=model)
    legacy_agent = KnowledgeAgent(load_legacy_curated(), llm=None)
    results = {"legacy_curated_bm25": evaluate(legacy_agent, questions, "bm25"),
               "snapshot_bm25": evaluate(new_agent, questions, "bm25")}
    if llm is not None:
        results["snapshot_dense"] = evaluate(new_agent, questions, "dense")
        results["snapshot_hybrid"] = evaluate(new_agent, questions, "hybrid")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = {"date": date.today().isoformat(), "commit": commit, "snapshot": snapshot.name if snapshot else None,
              "dataset": Path(args.dataset).name,
              "questions": len(questions), "min_relevance": MIN_RELEVANCE, "embedding_model": model,
              "summary": {k: {m: v for m, v in r.items() if m != "cases"} for k, r in results.items()}, "results": results}
    out = Path(args.output or f"retrieval-eval-{date.today().isoformat()}.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
