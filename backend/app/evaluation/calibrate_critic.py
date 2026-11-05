"""Critic and LLM judge versus human labels.

    python -m app.evaluation.calibrate_critic --output ../docs/eval/CRITIC_CALIBRATION_<date>.json

Inputs: docs/evaluation/labeling_items.jsonl (answers shown to the labeller, incl. injected
bad answers) and docs/evaluation/human_labels.jsonl. Positive class = "should be rejected"
(human label incorrect or unsafe; partially_correct is reported both ways).

Items are split deterministically (hash of item id) into a calibration half and a test half.
The only knob is CRITIC_STRICTNESS (material | strict); it is chosen by F1 on the
calibration half and reported on the test half, next to the other level.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path

from app.agents.critic_agent import CriticAgent
from app.evaluation.answer_quality import judge
from app.infra.llm import create_llm

ROOT = Path(__file__).resolve().parents[3]
REJECT_LABELS = {"incorrect", "unsafe"}


def half(item_id: str) -> str:
    return "calibration" if int(hashlib.sha256(item_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs: (predicted_reject, human_reject)."""
    tp = sum(p and h for p, h in pairs); fp = sum(p and not h for p, h in pairs)
    fn = sum(h and not p for p, h in pairs); tn = sum(not p and not h for p, h in pairs)
    n = len(pairs) or 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    po = (tp + tn) / n
    pe = ((tp + fp) / n) * ((tp + fn) / n) + ((tn + fn) / n) * ((tn + fp) / n)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    return {"n": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "accuracy": round(po, 4), "cohen_kappa": round(kappa, 4)}


def human_human_kappa(label_files: dict[str, dict[str, dict]]) -> dict | None:
    """Cohen's kappa between the first two labelers on items both of them labelled, on the
    4-way verdict (correct/partially_correct/incorrect/unsafe) and, when present, on the two
    guide dimensions (grounded, complete) separately."""
    names = list(label_files)
    if len(names) < 2:
        return None
    a_name, b_name = names[0], names[1]
    a, b = label_files[a_name], label_files[b_name]
    shared = sorted(set(a) & set(b))
    if not shared:
        return None

    def kappa_on(key: str) -> dict:
        pairs = [(a[i].get(key), b[i].get(key)) for i in shared if a[i].get(key) and b[i].get(key)]
        cats = sorted({v for pair in pairs for v in pair})
        n = len(pairs) or 1
        po = sum(x == y for x, y in pairs) / n
        pe = sum((sum(1 for x, _ in pairs if x == c) / n) * (sum(1 for _, y in pairs if y == c) / n) for c in cats)
        kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
        agree = sum(x == y for x, y in pairs)
        return {"n": len(pairs), "agreement": round(agree / n, 4), "cohen_kappa": round(kappa, 4)}

    return {"labeler_a": a_name, "labeler_b": b_name, "shared_items": len(shared),
            "verdict": kappa_on("label"), "grounded": kappa_on("grounded"), "complete": kappa_on("complete")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", default=str(ROOT / "docs" / "evaluation" / "labeling_items.jsonl"))
    parser.add_argument("--labels", nargs="+", default=[],
                         help="one or more human_labels_<labeler>.jsonl paths; default: every "
                              "docs/evaluation/human_labels_*.jsonl found, else the legacy human_labels.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args()
    items = {json.loads(l)["item_id"]: json.loads(l) for l in Path(args.items).read_text().splitlines() if l.strip()}
    label_paths = [Path(p) for p in args.labels] or sorted(ROOT.glob("docs/evaluation/human_labels_*.jsonl"))
    if not label_paths:
        legacy = ROOT / "docs" / "evaluation" / "human_labels.jsonl"
        label_paths = [legacy] if legacy.exists() else []
    label_files: dict[str, dict[str, dict]] = {}
    for path in label_paths:
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        labeler = rows[0]["labeler"] if rows and rows[0].get("labeler") else path.stem
        label_files[labeler] = {r["item_id"]: r for r in rows}
    # Reviewers are compared against the union of all labelers' labels; an item labelled by more
    # than one person keeps only the first labeler's verdict here (human_human_kappa below is
    # where multiple labelers are actually compared against each other).
    labels: dict[str, dict] = {}
    for rows in label_files.values():
        for item_id, row in rows.items():
            labels.setdefault(item_id, row)
    llm = create_llm()
    judge_llm = None
    if not args.no_judge:
        from app.infra.llm.anthropic_provider import AnthropicProvider
        judge_llm = AnthropicProvider()
        judge_llm.model = os.getenv("JUDGE_MODEL", "claude-sonnet-5-5")
        judge_llm.thinking = "omit"
        judge_llm.input_usd_per_mtok, judge_llm.output_usd_per_mtok = 2.0, 10.0
    rows = []
    for item_id, label in labels.items():
        item = items.get(item_id)
        if not item:
            continue
        evidence = item.get("evidence") or []
        tool_data = item.get("tool_data") or []
        verdicts = {}
        for level in ("material", "strict"):
            os.environ["CRITIC_STRICTNESS"] = level
            review = CriticAgent(llm, required=True).review(item["answer"], item["language"], evidence + tool_data,
                                                             user_message=item["question"], grounding_observations=tool_data or None)
            verdicts[level] = {"reject": review.get("approved") is False, "mode": review.get("mode"), "issues": review.get("issues")}
        row = {"item_id": item_id, "half": half(item_id), "injected": item.get("injected"), "human": label["label"],
               "human_reason": label.get("reason", ""), "critic": verdicts}
        if judge_llm is not None:
            try:
                j = judge(judge_llm, {"question": item["question"]}, item["answer"], evidence, tool_data)
                row["judge"] = {"verdict": j["verdict"], "reject": j["verdict"] in REJECT_LABELS}
            except Exception as exc:  # noqa: BLE001
                row["judge"] = {"error": type(exc).__name__}
        rows.append(row)
        print(item_id, label["label"], {k: v["reject"] for k, v in verdicts.items()}, (row.get("judge") or {}).get("verdict"), flush=True)
    os.environ["CRITIC_STRICTNESS"] = "material"

    def pairs(subset, who, level=None, partial_rejects=False):
        out = []
        for r in subset:
            human = r["human"] in REJECT_LABELS or (partial_rejects and r["human"] == "partially_correct")
            if who == "critic":
                out.append((r["critic"][level]["reject"], human))
            elif "reject" in (r.get("judge") or {}):
                out.append((r["judge"]["reject"], human))
        return out

    calib = [r for r in rows if r["half"] == "calibration"]
    test = [r for r in rows if r["half"] == "test"]
    chosen = max(("material", "strict"), key=lambda lv: metrics(pairs(calib, "critic", lv))["f1"])
    report = {
        "date": date.today().isoformat(),
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "labelers": list(label_files), "human_human_kappa": human_human_kappa(label_files),
        "labelled_items": len(rows), "calibration_items": len(calib), "test_items": len(test),
        "human_label_distribution": {lab: sum(1 for r in rows if r["human"] == lab) for lab in ("correct", "partially_correct", "incorrect", "unsafe")},
        "chosen_strictness_on_calibration_half": chosen,
        "critic": {lv: {"calibration": metrics(pairs(calib, "critic", lv)), "test": metrics(pairs(test, "critic", lv)),
                        "test_partial_counts_as_reject": metrics(pairs(test, "critic", lv, True))} for lv in ("material", "strict")},
        "judge": {"calibration": metrics(pairs(calib, "judge")), "test": metrics(pairs(test, "judge")),
                  "model": getattr(judge_llm, "model", None)},
        "demo_today": os.getenv("DEMO_TODAY"),
        # A Critic output that fails validation is a fail-closed rejection in production; here it is a
        # measurement failure, so it is counted and also excluded in a second view.
        "critic_invalid_outputs": {lv: sum(1 for r in rows if str(r["critic"][lv]["mode"]).startswith("llm_critic_invalid")
                                           or str(r["critic"][lv]["mode"]).startswith("llm_critic_unavailable")) for lv in ("material", "strict")},
        "critic_test_excluding_invalid": {lv: metrics(pairs([r for r in test if not str(r["critic"][lv]["mode"]).startswith(("llm_critic_invalid", "llm_critic_unavailable"))], "critic", lv))
                                          for lv in ("material", "strict")},
        # Injected bad answers have a known defect, independent of any label: detection by each reviewer.
        "injected_defect_detection": {
            "items": sum(1 for r in rows if r["injected"]),
            "critic_material_rejected": sum(1 for r in rows if r["injected"] and r["critic"]["material"]["reject"]),
            "critic_strict_rejected": sum(1 for r in rows if r["injected"] and r["critic"]["strict"]["reject"]),
            "judge_rejected": sum(1 for r in rows if r["injected"] and (r.get("judge") or {}).get("reject")),
            "human_flagged_incorrect_or_unsafe": sum(1 for r in rows if r["injected"] and r["human"] in REJECT_LABELS),
            "human_flagged_not_correct": sum(1 for r in rows if r["injected"] and r["human"] != "correct"),
        },
        "missed_by_critic_on_test": [{"item_id": r["item_id"], "human": r["human"], "injected": r["injected"], "reason": r["human_reason"]}
                                     for r in test if r["human"] in REJECT_LABELS and not r["critic"][chosen]["reject"]],
        "rows": rows,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
