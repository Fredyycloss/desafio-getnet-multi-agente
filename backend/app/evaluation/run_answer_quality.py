"""Answer quality of the live system (rubric: docs/evaluation/JUDGE_RUBRIC.md).

    python -m app.evaluation.run_answer_quality --output ../docs/eval/ANSWER_QUALITY_<mode>_<date>.json \
        [--judge] [--labeling-items ../docs/evaluation/labeling_items.jsonl] [--limit N]

Runs every item of answer_quality.jsonl through the real pipeline (ChatService with the configured
provider), then deterministic checks (coverage, forbidden facts, number grounding, citation
source, language, abstention) and, with --judge, an LLM judge of a different model
(JUDGE_MODEL, default claude-sonnet-5-5). --labeling-items also writes the answers (plus
deliberately broken variants) for human labelling with label_cli.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.evaluation.answer_quality import JUDGE_EVIDENCE_CHARS, deterministic_checks, judge
from app.infra.database import Database
from app.infra.llm import create_llm
from app.knowledge.ingest import load_documents, load_snapshot_vectors
from app.observability import finish_timeline, start_timeline
from app.service import ChatService

DATASET = Path(__file__).with_name("answer_quality.jsonl")
ABSTAIN_MODES = {"knowledge_scope_clarification", "context_policy_clarification", "clarification_required"}


def evidence_of(result: dict) -> tuple[list[dict], list]:
    evidence, tools = [], []
    for obs in result.get("specialist_observations") or []:
        for item in obs.get("evidence") or []:
            if isinstance(item, dict) and item.get("url") and item.get("content"):
                evidence.append(item)
            elif isinstance(item, dict):
                tools.append(item)
        tools.extend(obs.get("tool_observations") or [])
        if obs.get("tool_result"):
            tools.append(obs["tool_result"])
    return evidence, tools


ABSTAIN_TEXT = re.compile(
    r"n[aã]o (tenho|encontrei|h[aá]|consta|consigo confirmar|posso informar|[eé] poss[ií]vel (informar|confirmar|responder|determinar))"
    r"\b.{0,60}(informa|evid[eê]nci|dado|registro|fonte|base)"
    r"|could not find|no evidence|does not (state|contain|mention)|not (in|available in) the (evidence|sources)",
    re.IGNORECASE)


def abstained(result: dict) -> bool:
    """Policy abstention (menu, handoff) or an explicit "no evidence" answer written by the agent."""
    trace = result.get("trace") or []
    return (result.get("orchestration_mode") in ABSTAIN_MODES or "abstention" in trace or bool(result.get("handoff"))
            or result.get("intent") in {"clarification_required", "knowledge_scope_clarification"}
            or bool(ABSTAIN_TEXT.search(result.get("answer", ""))))


def injected_variants(bases: list[dict], rng: random.Random, total: int = 20) -> list[dict]:
    """Deliberately bad answers for human labelling and Critic calibration (~total items):
    invented number, wrong citation, off-topic answer, another customer's data, outdated fact."""
    out = []
    numeric = [b for b in bases if re.search(r"\d", b["answer"])]
    cited = [b for b in bases if "[1]" in b["answer"]]
    customer = [b for b in bases if b["item_id"].startswith("c0") and b["item_id"] != "c06"]

    def add(base, answer, kind):
        out.append({**base, "item_id": f"{base['item_id']}#{kind}", "answer": answer, "injected": kind})

    for base in rng.sample(numeric, min(7, len(numeric))):
        nums = re.findall(r"\d+(?:[.,]\d+)?", base["answer"])
        n = rng.choice(nums)
        bumped = str(int(float(n.replace(",", ".")) * 3 + 7)).replace(".", ",")
        add(base, base["answer"].replace(n, bumped, 1), "invented_number")
    for base in rng.sample(cited, min(4, len(cited))):
        add(base, base["answer"].replace("[1]", "[3]").replace("[2]", "[1]"), "wrong_citation")
    pool = [b for b in bases if not b["item_id"].startswith(("a0", "c0"))]
    for base in rng.sample(pool, min(3, len(pool))):
        other = rng.choice([b for b in pool if b["item_id"] != base["item_id"]])
        add(base, other["answer"], "off_topic")
    for base in rng.sample(customer, min(3, len(customer))):
        add(base, base["answer"] + " Também há a venda TX-DEMO-2001 de R$ 420,00 aprovada ontem.", "other_customer_data")
    swaps = [("48", "24"), ("2 dias", "30 dias"), ("15/01/2026", "15/01/2024"), ("12x", "6x"), ("Android 12", "Android 8")]
    stale = [(b, o, n) for b in bases for o, n in swaps if o in b["answer"]]
    for base, old, new in rng.sample(stale, min(3, len(stale))):
        add(base, base["answer"].replace(old, new), "outdated_fact")
    return out[:total]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--labeling-items", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--dataset", default=str(DATASET),
                         help="path to a .jsonl dataset (default: answer_quality.jsonl, the dev split); "
                              "pass answer_quality_test.jsonl or quality_test_v2.jsonl for the frozen splits")
    parser.add_argument("--rescore", default="", help="recompute deterministic checks of an existing report (no model calls)")
    parser.add_argument("--rejudge", default="", help="re-run only the judge on an existing report's answers, with full evidence chunks")
    args = parser.parse_args()
    items = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.rescore:
        report = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
        by_id = {it["id"]: it for it in items}
        for r in report["records"]:
            item = by_id[r["item_id"]]
            r["category"] = item["category"]
            r["checks"] = deterministic_checks(item, r["answer"], r["evidence"], r["tool_data"],
                                               abstained=abstained({"answer": r["answer"], "orchestration_mode": r["orchestration_mode"],
                                                                    "trace": r["trace"]}))
        records, llm, judge_llm = report["records"], None, None
        report_meta = {k: report.get(k) for k in ("commit", "provider", "model", "judge_model", "dataset")}
    if args.rejudge:
        records, report_meta = rejudge(Path(args.rejudge), items)
        finish(args, records, report_meta)
        return 0
    if args.limit:
        items = items[:args.limit]
    if not args.rescore:
        records, report_meta = run_live(args, items)
    finish(args, records, report_meta)
    return 0


def judge_provider():
    from app.infra.llm.anthropic_provider import AnthropicProvider
    os.environ.setdefault("JUDGE_MODEL", "claude-sonnet-5-5")
    judge_llm = AnthropicProvider()
    judge_llm.model = os.environ["JUDGE_MODEL"]
    judge_llm.thinking = "omit"  # Sonnet 5.5 rejects thinking=disabled; adaptive with low effort
    judge_llm.input_usd_per_mtok, judge_llm.output_usd_per_mtok = 2.0, 10.0  # claude-sonnet-5-5 list price
    return judge_llm


def rejudge(path: Path, items: list[dict]):
    """Judge again the recorded answers of a report. Stored evidence was cut at 900 chars, so each
    chunk is restored whole from the snapshot (matched by URL, section and the stored prefix)."""
    report = json.loads(path.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in items}
    full = {}
    for doc in load_documents():
        full.setdefault((doc.get("url"), doc.get("section")), []).append(doc.get("content", ""))
    judge_llm = judge_provider()
    restored = missing = 0
    for r in report["records"]:
        for e in r["evidence"]:
            stored = e.get("content", "")
            match = next((c for c in full.get((e.get("url"), e.get("section")), []) if c.startswith(stored[:200])), None)
            if match is not None:
                e["content"] = match[:JUDGE_EVIDENCE_CHARS]
                restored += 1
            else:
                missing += 1
        try:
            r["judge"] = judge(judge_llm, by_id[r["item_id"]], r["answer"], r["evidence"], r["tool_data"])
        except Exception as exc:  # noqa: BLE001 - a judge failure is recorded, not fatal
            r["judge"] = {"error": type(exc).__name__}
        print(f"[{r['item_id']}] judge={(r.get('judge') or {}).get('verdict')}", flush=True)
    meta = {k: report.get(k) for k in ("commit", "provider", "model", "judge_model", "dataset")}
    meta.update(rejudged_from=path.name, judge_evidence_chars=JUDGE_EVIDENCE_CHARS,
                evidence_chunks_restored=restored, evidence_chunks_not_found=missing)
    return report["records"], meta


def run_live(args, items):
    llm = create_llm()
    model, _, vectors = load_snapshot_vectors()
    db = Database(str(Path(tempfile.mkdtemp()) / "quality.sqlite3"))
    service = ChatService(load_documents(), db, llm, vectors=vectors, vector_model=model)
    judge_llm = judge_provider() if args.judge else None
    records = []
    for item in items:
        time.sleep(args.pause)
        token = start_timeline(uuid4().hex)
        started = time.perf_counter()
        try:
            result = service.answer(item["question"], item["user_id"], f"q-{item['id']}-{uuid4().hex[:6]}", [])
            from app.observability import current_timeline
            usage = current_timeline().model_usage()
        finally:
            finish_timeline(token)
        latency = time.perf_counter() - started
        evidence, tools = evidence_of(result)
        checks = deterministic_checks(item, result["answer"], evidence, tools, abstained=abstained(result))
        record = {"item_id": item["id"], "category": item["category"], "language": item["language"], "question": item["question"],
                  "answer": result["answer"], "orchestration_mode": result.get("orchestration_mode"), "trace": result.get("trace"),
                  "degraded": result.get("degraded"), "critic": result.get("critic"), "latency_s": round(latency, 2),
                  "sources": [{"title": s.get("title"), "url": s.get("url")} for s in result.get("sources") or []][:6],
                  # Stores every evidence item the model actually saw (not capped at 6): checks
                  # above were computed against the same full list, so a citation like [7] from a
                  # multi-specialist answer (e.g. Knowledge + Payments, >6 items combined) can be
                  # verified against stored evidence instead of silently reading as out-of-range
                  # on --rescore/--rejudge (found while measuring V8 Block 3, item m01).
                  "evidence": [{"title": e.get("title"), "url": e.get("url"), "section": e.get("section"), "content": e.get("content", "")[:JUDGE_EVIDENCE_CHARS]}
                               for e in evidence],
                  "tool_data": tools, "checks": checks,
                  "llm_calls": usage.get("llm_calls"), "cost_usd": usage.get("cost_usd", 0.0)}
        if judge_llm is not None:
            try:
                record["judge"] = judge(judge_llm, item, result["answer"], evidence, tools)
            except Exception as exc:  # noqa: BLE001 - a judge failure is recorded, not fatal
                record["judge"] = {"error": type(exc).__name__}
        records.append(record)
        print(f"[{item['id']}] {item['category']:14s} {latency:5.1f}s mode={record['orchestration_mode']} "
              f"cov={checks.get('coverage')} nums={checks.get('numbers_supported')} judge={(record.get('judge') or {}).get('verdict')}", flush=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    return records, {"commit": commit, "provider": getattr(llm, "provider", None), "model": getattr(llm, "model", None),
                     "judge_model": getattr(judge_llm, "model", None), "dataset": Path(args.dataset).name}


def aggregate(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["checks"]["kind"] == "answer"]
    abst = [r for r in rows if r["checks"]["kind"] == "abstain"]
    judged = [r["judge"] for r in rows if isinstance(r.get("judge"), dict) and "verdict" in r["judge"]]
    mean = lambda xs: round(statistics.mean(xs), 4) if xs else None  # noqa: E731
    return {
        "n": len(rows),
        "coverage_mean": mean([r["checks"]["coverage"] for r in ans if r["checks"]["coverage"] is not None]),
        "full_coverage_rate": mean([1.0 if r["checks"]["coverage"] == 1 else 0.0 for r in ans if r["checks"]["coverage"] is not None]),
        "forbidden_absent_rate": mean([1.0 if r["checks"]["forbidden_absent"] else 0.0 for r in rows]),
        "numbers_supported_rate": mean([1.0 if r["checks"]["numbers_supported"] else 0.0 for r in ans]),
        "citation_correct_rate": mean([1.0 if r["checks"]["citation_correct"] else 0.0 for r in ans if r["checks"]["citation_correct"] is not None]),
        "language_ok_rate": mean([1.0 if r["checks"]["language_ok"] else 0.0 for r in rows]),
        "abstention_correct_rate": mean([1.0 if r["checks"]["abstention_correct"] else 0.0 for r in abst]),
        "degraded_rate": mean([1.0 if r["degraded"] else 0.0 for r in rows]),
        "critic_rejection_rate": mean([1.0 if (r.get("critic") or {}).get("approved") is False else 0.0 for r in rows]),
        "judge_correct_rate": mean([1.0 if j["verdict"] == "correct" else 0.0 for j in judged]),
        "judge_grounded_rate": mean([1.0 if j.get("grounded") else 0.0 for j in judged]),
        "judge_usefulness_mean": mean([j["usefulness"] for j in judged if isinstance(j.get("usefulness"), int)]),
        "latency_mean_s": mean([r["latency_s"] for r in rows]),
    "latency_p95_s": sorted(r["latency_s"] for r in rows)[max(0, int(round(0.95 * len(rows))) - 1)] if rows else None,
    "llm_calls_mean": mean([r["llm_calls"] for r in rows if r.get("llm_calls") is not None]),
    "cost_mean_usd": mean([r["cost_usd"] for r in rows if r.get("cost_usd") is not None]),
    }


def finish(args, records, meta):

    agg = aggregate
    by_cat = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r)
    report = {"date": date.today().isoformat(), **meta, "rescored": bool(args.rescore),
              "items": len(records), "overall": agg(records), "by_category": {k: agg(v) for k, v in sorted(by_cat.items())},
              "records": records}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report["overall"], indent=2))
    if args.labeling_items:
        rng = random.Random(7)
        bases = []
        for r in records:
            bases.append({"item_id": r["item_id"], "language": r["language"], "question": r["question"], "answer": r["answer"],
                          "sources": [{"title": e["title"], "url": e["url"], "excerpt": e["content"][:400]} for e in r["evidence"][:4]],
                          "customer_context": json.dumps(r["tool_data"][:3], ensure_ascii=False, default=str)[:600] if r["tool_data"] else "",
                          "tool_data": r["tool_data"][:6], "evidence": r["evidence"][:6], "injected": None})
        out = bases + injected_variants(bases, rng)
        rng.shuffle(out)
        Path(args.labeling_items).write_text("".join(json.dumps(o, ensure_ascii=False, default=str) + "\n" for o in out), encoding="utf-8")
        print(f"labeling items: {len(out)} → {args.labeling_items}")


if __name__ == "__main__":
    raise SystemExit(main())
