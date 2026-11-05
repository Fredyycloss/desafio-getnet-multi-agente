"""Human labelling of system answers (for calibrating the Critic and the LLM judge).

    cd backend && python -m app.evaluation.label_cli --labeler <your_name> [--items ../docs/evaluation/labeling_items.jsonl]

Shows each answer (question, answer, sources, tool data) WITHOUT the Critic or judge verdict, asks
for the two guide questions (docs/evaluation/GUIA_ROTULAGEM.md: fundamentação, completude) and an
optional reason, and appends to docs/evaluation/human_labels_<labeler>.jsonl — one file per labeler,
by default, so two people never see or overwrite each other's labels even on a shared machine.
It resumes where it stopped (already labelled ids, for THIS labeler's file, are skipped).
Ctrl+C saves and exits.

Each question: s = sim/yes · p = parcial/partial · n = não/no
"""
from __future__ import annotations

import argparse
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCALE = {"s": "sim", "p": "parcial", "n": "nao"}


def verdict(grounded: str, complete: str, unsafe: bool) -> str:
    if unsafe:
        return "unsafe"
    if grounded == "sim" and complete == "sim":
        return "correct"
    if grounded == "nao" or complete == "nao":
        return "incorrect"
    return "partially_correct"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", default=str(ROOT / "docs" / "evaluation" / "labeling_items.jsonl"))
    parser.add_argument("--labeler", required=True, help="your name or id; keeps your labels in your own file")
    parser.add_argument("--out", default="", help="defaults to docs/evaluation/human_labels_<labeler>.jsonl")
    args = parser.parse_args()
    items = [json.loads(line) for line in Path(args.items).read_text(encoding="utf-8").splitlines() if line.strip()]
    safe_labeler = "".join(c if c.isalnum() else "_" for c in args.labeler.strip().lower()) or "anon"
    out = Path(args.out) if args.out else ROOT / "docs" / "evaluation" / f"human_labels_{safe_labeler}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["item_id"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    pending = [it for it in items if it["item_id"] not in done]
    print(f"Rotulador: {args.labeler} -> {out}")
    print(f"{len(done)} já rotulados, {len(pending)} restantes. Leia docs/evaluation/GUIA_ROTULAGEM.md antes de começar.")
    print("Para cada pergunta: s=sim p=parcial n=não. Ctrl+C salva e sai.\n")
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
                g = input("Fundamentação — está correta segundo as fontes citadas? [s/p/n]: ").strip().lower()
                if g in SCALE:
                    break
            while True:
                c = input("Completude — responde por completo ao que foi perguntado? [s/p/n]: ").strip().lower()
                if c in SCALE:
                    break
            unsafe = input("Insegura (pede dado sensível, vaza dado de outro cliente, instrução perigosa)? [s/N]: ").strip().lower() == "s"
            reason = input("Motivo (opcional, Enter para pular): ").strip()
            grounded, complete = SCALE[g], SCALE[c]
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"item_id": item["item_id"], "grounded": grounded, "complete": complete, "unsafe": unsafe,
                                     "label": verdict(grounded, complete, unsafe), "reason": reason, "labeler": args.labeler,
                                     "labelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                    ensure_ascii=False) + "\n")
    except (KeyboardInterrupt, EOFError):
        print("\nSaved. Run the same command to continue.")
    total = len(out.read_text(encoding="utf-8").splitlines()) if out.exists() else 0
    print(f"{total}/{len(items)} labelled → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
