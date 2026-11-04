#!/usr/bin/env python3
"""Export a recorded cloud run into docs/evidence/cloud_runs/<date>/.

    python3 scripts/export_cloud_run.py --date 2026-11-04 --report docs/RELATORIO_LATENCIA_<...>.json

1. copies the cassette written by the API (LLM_RECORD_DIR=/data/cassettes/<date>) out of the
   container with `docker compose cp` and stores it gzip-compressed;
2. checks the cassette and turns.jsonl for credentials (Anthropic key prefix, bearer tokens,
   Telegram token shape, and the values of the secret variables present in this process's
   environment, compared only, never printed) and refuses to export on any hit;
3. writes manifest.json: commit, model, counts per purpose, tokens, cost, file list.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_PREFIX = "sk-" + "ant-"  # split so the literal never appears in the repository (pre-push check)
FORBIDDEN = [re.compile(re.escape(KEY_PREFIX) + r"[A-Za-z0-9_-]{8,}"), re.compile(r"Bearer\s+[A-Za-z0-9_.-]{20,}"),
             re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")]  # Telegram bot token shape


def secret_values() -> list[str]:
    values = []
    for name in ("GETNET_ANTHROPIC_API_KEY", "AUTH_SECRET", "TELEGRAM_BOT_TOKEN", "OPERATOR_API_KEY"):
        v = os.getenv(name, "").strip()
        if len(v) >= 8:
            values.append(v)
    return values


def scan(text: str, secrets: list[str]) -> list[str]:
    hits = [p.pattern[:20] for p in FORBIDDEN if p.search(text)]
    hits += ["configured_secret_value" for s in secrets if s in text]
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True)
    parser.add_argument("--report", required=True, help="benchmark report JSON of the same run")
    parser.add_argument("--service", default="api")
    parser.add_argument("--commit", default="", help="commit the API image was built from (default: HEAD)")
    args = parser.parse_args()
    out = ROOT / "docs" / "evidence" / "cloud_runs" / args.date
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cp = subprocess.run(["docker", "compose", "cp", f"{args.service}:/data/cassettes/{args.date}/cassette.jsonl", f"{tmp}/cassette.jsonl"],
                            cwd=ROOT, capture_output=True, text=True)
        if cp.returncode != 0:
            print(cp.stderr[-400:], file=sys.stderr)
            return 1
        raw = Path(tmp, "cassette.jsonl").read_text(encoding="utf-8")
    turns_path = out / "turns.jsonl"
    turns_text = turns_path.read_text(encoding="utf-8") if turns_path.exists() else ""
    secrets = secret_values()
    hits = scan(raw, secrets) + scan(turns_text, secrets)
    if hits:
        print(f"refusing to export: credential pattern found ({sorted(set(hits))})", file=sys.stderr)
        return 2
    with gzip.open(out / "cassette.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(raw)
    entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
    chats = [e for e in entries if e["kind"] == "chat"]
    purposes = collections.Counter(e["purpose"] for e in chats)
    usage = [e["response"].get("usage") or {} for e in chats]
    turns = [json.loads(line) for line in turns_text.splitlines() if line.strip()]
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    shutil.copy(args.report, out / "benchmark_report.json")
    manifest = {
        "date": args.date,
        "commit": args.commit or subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "provider": sorted({e["response"].get("provider") for e in chats}),
        "models": sorted({e["response"].get("model") for e in chats}),
        "health_at_start": report.get("health"),
        "files": {
            "turns.jsonl": "one line per /api/chat call: scenario, question, HTTP status, latency and the full response "
                           "(answer, sources, trace, stage timings, specialist observations with tool arguments/results, "
                           "Critic verdict, model_usage)",
            "cassette.jsonl.gz": "every model call: masked request key, purpose, messages sent, tool names, response, tokens. "
                                 "Used by LLM_PROVIDER=replay",
            "benchmark_report.json": "the benchmark report of this run (latency, acceptance 1-18, orchestration)",
        },
        "counts": {"chat_turns": len(turns), "model_calls": len(chats), "embedding_calls": len(entries) - len(chats),
                   "model_calls_by_purpose": dict(purposes.most_common())},
        "tokens": {"prompt": sum(u.get("prompt_tokens") or 0 for u in usage), "output": sum(u.get("output_tokens") or 0 for u in usage)},
        "cost_usd": round(sum(u.get("cost_usd") or 0 for u in usage), 6),
        "privacy": "Synthetic demo customers only. Credential scan (key prefix, bearer tokens, configured secret values) passed before export.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("commit", "models", "counts", "tokens", "cost_usd")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
