"""V7-H: does the session memory keep facts from early turns of a long conversation?

    python -m app.evaluation.run_memory_eval --output ../docs/eval/MEMORY_EVAL_<date>.json

Four conversations (pt/en), written for this test: turn 1 states a fact, 14 unrelated questions
follow, the last turn asks about turn 1. Each conversation runs twice through the real API
(in-process, configured provider): SESSION_MEMORY=on and off. Without memory the agents only see
the last messages, so turn 1 is gone by the end. Reported per mode: facts recalled in the final
answer, prompt tokens of the final turn, the context the memory replaced (characters) versus the
memory note, and the tokens/cost of the background summary calls.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path

FILLERS_PT = [
    "Quais bandeiras de cartão a Getnet aceita?", "Como funciona o Pix na maquininha?", "A Getnet tem conta digital?",
    "Posso parcelar vendas no cartão de crédito?", "O que é antecipação de recebíveis?", "Como acesso o portal do cliente?",
    "A maquininha imprime comprovante?", "Existe taxa de adesão?", "Como faço para trocar a bobina?",
    "Qual o prazo de recebimento no débito?", "A Getnet atende MEI?", "Como funciona o link de pagamento?",
    "Posso vender por aproximação?", "Como falo com o suporte técnico?",
]
FILLERS_EN = [
    "Which card brands does Getnet accept?", "How does Pix work on the card machine?", "Does Getnet offer a digital account?",
    "Can I split credit card sales into installments?", "What is receivables advance?", "How do I access the customer portal?",
    "Does the terminal print receipts?", "Is there a sign-up fee?", "How do I change the paper roll?",
    "How long does a debit sale take to settle?", "Does Getnet serve sole proprietors?", "How does the payment link work?",
    "Can I take contactless payments?", "How do I reach technical support?",
]
CONVERSATIONS = [
    {"id": "store_and_model", "language": "pt", "first": "Oi! Meu estabelecimento se chama Doceria Primavera e uso uma Get Mini no balcão.",
     "last": "Lembra o nome do meu estabelecimento e qual maquininha eu disse que uso?", "expect": ["Doceria Primavera", "Get Mini"]},
    {"id": "terminal_problem", "language": "pt", "first": "A minha maquininha TERM-1988 está sem internet desde ontem à tarde.",
     "last": "Qual era o terminal que eu disse que estava com problema?", "expect": ["TERM-1988"]},
    {"id": "chosen_product", "language": "pt", "first": "Estou decidindo entre a Get Smart e a Get Clássica; vou ficar com a Get Clássica.",
     "last": "Qual modelo eu disse que escolhi no começo da conversa?", "expect": ["Get Clássica"]},
    {"id": "shop_name_en", "language": "en", "first": "Hi! My shop is called Blue Harbor Café and most of my customers pay by Pix.",
     "last": "What is the name of my shop that I told you at the start?", "expect": ["Blue Harbor"]},
]


def run(mode: str) -> dict:
    os.environ["SESSION_MEMORY"] = mode
    os.environ["DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / f"memory-{mode}.sqlite3")
    os.environ.setdefault("CHAT_MAX_REQUESTS_PER_MINUTE", "1000")
    from fastapi.testclient import TestClient
    from app.main import app, state
    out = []
    summary_usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    with TestClient(app) as client:
        memory = state["service"].memory
        inner = memory.llm

        class Counting:  # counts the background summary calls (they run outside the request timeline)
            def __getattr__(self, name):
                return getattr(inner, name)

            def chat(self, *a, **k):
                r = inner.chat(*a, **k)
                u = r.get("usage") or {}
                summary_usage["calls"] += 1
                summary_usage["prompt_tokens"] += u.get("prompt_tokens") or 0
                summary_usage["output_tokens"] += u.get("output_tokens") or 0
                summary_usage["cost_usd"] += u.get("cost_usd") or 0.0
                return r
        if inner is not None:
            memory.llm = Counting()
        token = client.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for conv in CONVERSATIONS:
            session = f"mem-{mode}-{conv['id']}"
            fillers = FILLERS_PT if conv["language"] == "pt" else FILLERS_EN
            for text in [conv["first"], *fillers]:
                client.post("/api/chat", json={"message": text, "user_id": "cliente1988", "session_id": session}, headers=headers)
            final = client.post("/api/chat", json={"message": conv["last"], "user_id": "cliente1988", "session_id": session},
                                headers=headers).json()
            answer = final.get("answer", "")
            recalled = [fact for fact in conv["expect"] if fact.casefold() in answer.casefold()]
            usage = final.get("model_usage") or {}
            out.append({"id": conv["id"], "recalled_all": len(recalled) == len(conv["expect"]), "recalled": recalled,
                        "expected": conv["expect"], "answer": answer[:400], "memory": final.get("memory"),
                        "final_turn_prompt_tokens": usage.get("prompt_tokens"), "final_turn_cost_usd": usage.get("cost_usd")})
            print(f"  [{mode}] {conv['id']:18s} recalled={recalled} memory={final.get('memory')}", flush=True)
    n = len(out)
    return {"conversations": out, "recall_rate": round(sum(r["recalled_all"] for r in out) / n, 4),
            "mean_final_prompt_tokens": round(sum(r["final_turn_prompt_tokens"] or 0 for r in out) / n, 1),
            "summary_calls": summary_usage}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    os.environ.setdefault("KNOWLEDGE_LIVE_READ", "false")
    report = {"date": date.today().isoformat(),
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
              "turns_per_conversation": 1 + len(FILLERS_PT) + 1,
              "settings": {k: os.getenv(k) for k in ("SESSION_SUMMARY_AFTER_MESSAGES", "SESSION_MEMORY_RECENT_MESSAGES")}}
    for mode in ("on", "off"):
        print(f"== SESSION_MEMORY={mode}", flush=True)
        report[mode] = run(mode)
    on = [r["memory"] for r in report["on"]["conversations"] if (r.get("memory") or {}).get("memory_used")]
    if on:
        report["context_compression"] = {
            "mean_chars_replaced": round(sum(m["chars_replaced"] for m in on) / len(on), 1),
            "mean_memory_note_chars": round(sum(m["memory_chars"] for m in on) / len(on), 1)}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("on", "off")} | {
        "recall_on": report["on"]["recall_rate"], "recall_off": report["off"]["recall_rate"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
