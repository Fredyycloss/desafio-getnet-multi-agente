"""Human labelling of system answers (for calibrating the Critic and the LLM judge).

    cd backend && python -m app.evaluation.label_cli [--items ../docs/evaluation/labeling_items.jsonl]

Shows each answer (question, answer, sources, tool data) WITHOUT the Critic or judge verdict,
asks for one label and an optional reason, and appends to docs/evaluation/human_labels.jsonl.
It resumes where it stopped (already labelled ids are skipped). Ctrl+C saves and exits.

Labels: c = correct · p = partially correct · i = incorrect · u = unsafe (should never be sent)
"""
from __future__ import annotations

import argparse
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LABELS = {"c": "correct", "p": "partially_correct", "i": "incorrect", "u": "unsafe"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", default=str(ROOT / "docs" / "evaluation" / "labeling_items.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "evaluation" / "human_labels.jsonl"))
    parser.add_argument("--labeler", default="human_1")
    args = parser.parse_args()
    items = [json.loads(line) for line in Path(args.items).read_text(encoding="utf-8").splitlines() if line.strip()]
    out = Path(args.out)
    done = set()
    if out.exists():
        done = {json.loads(line)["item_id"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    pending = [it for it in items if it["item_id"] not in done]
    print(f"{len(done)} already labelled, {len(pending)} to go. Labels: c=correct p=partial i=incorrect u=unsafe. Ctrl+C to stop.\n")
    wrap = lambda text: textwrap.fill(str(text), width=110, subsequent_indent="   ")  # noqa: E731
    try:
        for n, item in enumerate(pending, start=1):
            print("=" * 110)
            print(f"[{len(done) + n}/{len(items)}] {item['item_id']}  ({item.get('language', 'pt')})")
            print(wrap(f"PERGUNTA: {item['question']}"))
            if item.get("customer_context"):
                print(wrap(f"CONTEXTO DO CLIENTE (dados das ferramentas): {item['customer_context']}"))
            print()
            print(wrap(f"RESPOSTA: {item['answer']}"))
            for i, src in enumerate(item.get("sources", [])[:5], start=1):
                print(wrap(f"   fonte [{i}] {src.get('title', '')} — {src.get('url', '')}"))
                if src.get("excerpt"):
                    print(wrap(f"        trecho: {src['excerpt'][:400]}"))
            print()
            while True:
                choice = input("Rótulo [c/p/i/u]: ").strip().lower()
                if choice in LABELS:
                    break
            reason = input("Motivo (opcional, Enter para pular): ").strip()
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"item_id": item["item_id"], "label": LABELS[choice], "reason": reason, "labeler": args.labeler,
                                     "labelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                    ensure_ascii=False) + "\n")
    except (KeyboardInterrupt, EOFError):
        print("\nSaved. Run the same command to continue.")
    total = len(out.read_text(encoding="utf-8").splitlines()) if out.exists() else 0
    print(f"{total}/{len(items)} labelled → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
