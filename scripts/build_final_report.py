#!/usr/bin/env python3
"""Build docs/RELATORIO_FINAL_<date>.md from the measured JSON reports (no number is typed by hand).

    python3 scripts/build_final_report.py --date 2026-11-02 [--extra docs/notes.md]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def pct(value) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def sec(value) -> str:
    return "—" if value is None else f"{value:.1f} s"


def eval_rows(date: str) -> list[str]:
    rows = ["| Mode | Split | Cases | Risk acc. | Action acc. | Route acc. | Clarif. F1 | Safety FN rate | Safety misses | Invalid JSON | Mean / p95 latency | Cost |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for mode in ("anthropic", "ollama"):
        for split in ("dev", "heldout"):
            r = load(DOCS / "eval" / f"CONTEXT_EVAL_{split}_{mode}_{date}.json")
            if not r:
                rows.append(f"| {mode} | {split} | not measured | | | | | | | | | |")
                continue
            route = pct(r.get("route_accuracy")) if r.get("route_cases") else "n/a"
            rows.append(
                f"| {r['provider']} ({r['model']}) | {split} | {r['dataset_size']} | {pct(r['risk_accuracy'])} | {pct(r['action_accuracy'])} | "
                f"{route} | {r['clarification_f1']:.2f} | {pct(r['safety_false_negative_rate'])} | {len(r.get('safety_misses', []))} | "
                f"{r['json_invalid_count']} | {r['mean_latency_ms'] / 1000:.1f} / {r['p95_latency_ms'] / 1000:.1f} s | US$ {r.get('total_cost_usd', 0):.4f} |")
    return rows


def eval_failures(date: str) -> list[str]:
    out = []
    for mode in ("anthropic", "ollama"):
        r = load(DOCS / "eval" / f"CONTEXT_EVAL_heldout_{mode}_{date}.json")
        if not r:
            continue
        wrong = [c for c in r["cases"] if not (c["risk_pass"] and c["action_pass"])]
        out.append(f"**{mode} — held-out cases with wrong risk or action ({len(wrong)}/{r['dataset_size']}):**")
        out.append("")
        for c in wrong:
            out.append(f"- `{c['id']}` ({c['category']}): risk {c['expected_risk']} → {c['actual_risk']}; "
                       f"action {c['expected_action']} → {c['actual_action']}")
        out.append("")
    return out


def bench_section(label: str) -> list[str]:
    r = load(DOCS / f"RELATORIO_LATENCIA_{label}.json")
    if not r:
        return [f"_{label}: not measured._", ""]
    s = r["latency_summary"]["warm"]
    lat = s["llm_complete_latency"]
    records = r["rounds"]["warm"]
    # Recomputed from per-turn records so reports made before these metrics existed are comparable.
    escalated = [x["id"] for x in records if "critic_recheck" in (x.get("trace") or []) and "human_escalation_agent" in (x.get("trace") or [])]
    s["critic_escalations"] = escalated
    s["answered_by_agents_rate"] = sum(1 for x in records if x["outcome"] == "llm_complete" and x["id"] not in escalated) / max(len(records), 1)
    provider = (r["health"].get("llm_provider") or {})
    out = [f"### {provider.get('provider')} — `{provider.get('model')}` (budget {r['health'].get('request_llm_budget_seconds')} s)", "",
           f"Report: [`{Path('RELATORIO_LATENCIA_' + label + '.json')}`](RELATORIO_LATENCIA_{label}.json). {r.get('note', '')}", "",
           "| Metric | Value |", "|---|---|",
           f"| Latency requests | {s['requests']} |",
           f"| Outcomes | {', '.join(f'{k}={v}' for k, v in s['outcomes'].items())} |",
           f"| Success (llm_complete) / fallback / HTTP error | {pct(s['success_rate'])} / {pct(s['fallback_rate'])} / {pct(s['error_rate'])} |",
           f"| Degraded rate | {pct(s.get('degraded_rate'))} |",
           f"| Route correct (challenge + D1/D2) | {s['route_correct']} |",
           f"| Critic reviews / rejection rate | {s.get('critic_reviews')} / {pct(s.get('critic_rejection_rate'))} |",
           f"| Escalated to a human after two Critic rejections | {len(s.get('critic_escalations', []))} {s.get('critic_escalations') or ''} |",
           f"| Answered by agents (complete, not escalated) | {pct(s.get('answered_by_agents_rate'))} |",
           f"| Mean / p95 latency (llm_complete) | {sec(lat.get('mean_s'))} / {sec(lat.get('p95_s'))} |",
           f"| LLM calls per turn (mean) | {lat.get('mean_llm_calls')} |",
           f"| Tokens per turn (mean prompt / output) | {lat.get('mean_prompt_tokens')} / {lat.get('mean_output_tokens')} |",
           f"| Cost per turn (mean) | US$ {s.get('mean_cost_usd_per_turn', 0):.6f} |", "",
           "| Category (target) | n | complete | mean | p95 | within target |", "|---|---|---|---|---|---|"]
    for cat, v in s["by_category"].items():
        out.append(f"| {cat} (≤{v['target_s']} s) | {v['n']} | {v['llm_complete']} | {sec(v.get('mean_s'))} | {sec(v.get('p95_s'))} | "
                   f"{v['llm_complete_within_target']}/{v['llm_complete']} |")
    out += ["", "| Scenario | latency | outcome | route | LLM calls | mode | Critic |", "|---|---|---|---|---|---|---|"]
    for rec in r["rounds"]["warm"]:
        critic = f"{rec.get('critic_mode')}:{'ok' if rec.get('critic_approved') else 'rejected'}" if rec.get("critic_mode") else "—"
        out.append(f"| {rec['id']} | {rec['latency_s']:.1f} s | {rec['outcome']} | {rec.get('route_ok') if rec.get('route_ok') is not None else '—'} | "
                   f"{rec.get('llm_calls')} | {rec.get('orchestration_mode')} | {critic} |")
    out += ["", "**Acceptance 1–18:**", ""]
    for name, items in r.get("acceptance_map_1_18", {}).items():
        out.append(f"- {name}: " + ", ".join(f"{sid} **{verdict}**" for sid, verdict in items.items()))
    failing = [(n, a) for n, a in r["acceptance"].items() if not a["pass"]]
    if failing:
        out += ["", "**Failed checks:**", ""]
        for name, item in failing:
            for check in item["checks"]:
                if not check["pass"]:
                    out.append(f"- {name} → `{check['check']}`: {json.dumps(check.get('detail'), ensure_ascii=False)[:200]}")
    return out + [""]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--extra", default="", help="markdown file appended verbatim (method notes, clean clone)")
    args = parser.parse_args()
    lines = [f"# Final report — {args.date}", "",
             "Generated by `scripts/build_final_report.py` from the JSON reports in `docs/` and `docs/eval/`. "
             "Host: Intel i3 (4 threads), 8 GB RAM, no GPU. Same code in both modes; only `LLM_PROVIDER` differs.", "",
             "## 1. Context Intelligence (dev vs held-out)", "",
             "The held-out set (44 cases) was written before the stage-A prompt rewrite and never used for tuning.", "",
             *eval_rows(args.date), "", *eval_failures(args.date),
             "## 2. End-to-end benchmark (real HTTP, demo tokens, warm round)", "",
             "Latency mean/p95 use `llm_complete` responses only; fallbacks and errors are failures. Targets: simple ≤10 s, tools ≤15 s, complex ≤25 s.", "",
             *bench_section(f"{args.date}_anthropic"),
             *bench_section(f"{args.date}_ollama"),
             "### Earlier cloud run (before Critic calibration)", "",
             *bench_section(f"{args.date}_anthropic-critic-v1")[2:16], ""]
    if args.extra:
        lines += [Path(args.extra).read_text(encoding="utf-8")]
    out = DOCS / f"RELATORIO_FINAL_{args.date}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
