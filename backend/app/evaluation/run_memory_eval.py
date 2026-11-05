"""V7-H / V8 Block 9: does the session memory keep facts from early turns of a long conversation?

    python -m app.evaluation.run_memory_eval --output ../docs/eval/MEMORY_EVAL_<date>.json [--judge]

30 conversations (pt/en), written for this test: turn 1 states a fact, 14 unrelated questions
follow, the last turn asks about turn 1. Each conversation runs twice through the real API
(in-process, configured provider): SESSION_MEMORY=on and off. Without memory the agents only see
the last messages, so turn 1 is gone by the end. Reported per mode: facts recalled in the final
answer, prompt tokens of the final turn, the context the memory replaced (characters) versus the
memory note, and the tokens/cost of the background summary calls.

--judge adds an LLM check (claude-haiku-5-5) on top of the keyword match: the keyword check alone
can be fooled both ways — a coincidental mention of the expected word inflates a "recalled" count
in the off condition, and a correct paraphrase (e.g. the fact stated in different words) deflates
a real recall in the on condition. The judge sees only the first message and the final answer
(never the fillers or which mode produced it) and says whether the answer demonstrates the model
actually remembers that specific fact.
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
    # Added 05/11/2026 (the first 4 were too few to conclude anything).
    {"id": "city_pt", "language": "pt", "first": "Minha loja fica em Joinville, no centro da cidade.",
     "last": "Em que cidade eu falei que fica a minha loja?", "expect": ["Joinville"]},
    {"id": "owner_name_pt", "language": "pt", "first": "Aqui é a Renata, sou dona de um pet shop pequeno.",
     "last": "Você lembra o meu nome?", "expect": ["Renata"]},
    {"id": "business_type_en", "language": "en", "first": "I run a small bike repair shop near the river.",
     "last": "What kind of business did I tell you I run?", "expect": ["bike"]},
    {"id": "payment_pref_pt", "language": "pt", "first": "A maioria dos meus clientes paga no débito, quase ninguém usa crédito.",
     "last": "Qual forma de pagamento eu disse que meus clientes mais usam?", "expect": ["débito"]},
    {"id": "open_days_en", "language": "en", "first": "We only open on weekends, Saturday and Sunday.",
     "last": "Which days did I say we are open?", "expect": ["Saturday"]},
    {"id": "product_interest_en", "language": "en", "first": "I'm interested in the Payment Link for my online orders.",
     "last": "Which Getnet product did I say I was interested in?", "expect": ["Payment Link"]},
    {"id": "employee_pt", "language": "pt", "first": "Quem opera a maquininha é o meu funcionário Tiago.",
     "last": "Qual é o nome do funcionário que eu disse que opera a maquininha?", "expect": ["Tiago"]},
    {"id": "region_en", "language": "en", "first": "My café is in Curitiba and I'm thinking of opening a second one.",
     "last": "In which city did I say my café is?", "expect": ["Curitiba"]},
    # Added 05/11/2026 for V8 Block 9 (mission wants >=30 conversations).
    {"id": "employee_count_pt", "language": "pt", "first": "Minha loja tem 7 funcionários no total, contando comigo.",
     "last": "Quantos funcionários eu disse que minha loja tem?", "expect": ["7"]},
    {"id": "opening_year_pt", "language": "pt", "first": "Abri meu restaurante em 2019, antes da pandemia.",
     "last": "Em que ano eu disse que abri meu restaurante?", "expect": ["2019"]},
    {"id": "competitor_en", "language": "en", "first": "I used to work with a different acquirer before switching to Getnet last year.",
     "last": "Did I mention switching to Getnet from somewhere else? When did I say that happened?", "expect": ["last year"]},
    {"id": "ticket_size_pt", "language": "pt", "first": "O ticket médio das minhas vendas fica em torno de R$ 85.",
     "last": "Qual valor eu disse que é o ticket médio das minhas vendas?", "expect": ["85"]},
    {"id": "neighborhood_en", "language": "en", "first": "My store is in the Pinheiros neighborhood of São Paulo.",
     "last": "Which neighborhood did I say my store is in?", "expect": ["Pinheiros"]},
    {"id": "complaint_detail_pt", "language": "pt", "first": "Minha reclamação é que o comprovante saiu com a data errada na semana passada.",
     "last": "Qual foi o problema que eu relatei no comprovante?", "expect": ["data"]},
    {"id": "second_location_pt", "language": "pt", "first": "Tenho duas lojas: uma no shopping e outra na rua principal.",
     "last": "Quantas lojas eu disse que tenho e onde elas ficam?", "expect": ["duas"]},
    {"id": "preferred_contact_en", "language": "en", "first": "Please always reach me by WhatsApp, I rarely check email.",
     "last": "How did I say I prefer to be contacted?", "expect": ["WhatsApp"]},
    {"id": "machine_count_pt", "language": "pt", "first": "Uso três maquininhas Get Smart, uma em cada caixa.",
     "last": "Quantas maquininhas eu disse que uso e qual modelo?", "expect": ["três", "Get Smart"]},
    {"id": "business_hours_pt", "language": "pt", "first": "Minha loja funciona das 9h às 19h, de segunda a sábado.",
     "last": "Qual o horário de funcionamento que eu informei?", "expect": ["9h"]},
    {"id": "franchise_en", "language": "en", "first": "My bakery is part of a small franchise with three other units in the city.",
     "last": "What kind of business arrangement did I describe for my bakery?", "expect": ["franchise"]},
    {"id": "card_brand_pref_pt", "language": "pt", "first": "A maioria das vendas aqui é no cartão Elo, bem mais que Visa ou Mastercard.",
     "last": "Qual bandeira de cartão eu disse que é mais usada na minha loja?", "expect": ["Elo"]},
    {"id": "delivery_only_en", "language": "en", "first": "We are a delivery-only kitchen, we don't have a physical storefront.",
     "last": "Did I say my business has a physical storefront or is delivery-only?", "expect": ["delivery"]},
    {"id": "supplier_name_pt", "language": "pt", "first": "Meu principal fornecedor se chama Distribuidora Vale Verde.",
     "last": "Qual o nome do meu principal fornecedor que eu mencionei?", "expect": ["Vale Verde"]},
    {"id": "goal_revenue_en", "language": "en", "first": "My goal this year is to double my monthly revenue to around $20,000.",
     "last": "What revenue goal did I mention for this year?", "expect": ["20,000", "20000", "double"]},
    {"id": "seasonal_pt", "language": "pt", "first": "Minhas vendas sobem muito no Natal e caem bastante em fevereiro.",
     "last": "Em quais períodos eu disse que minhas vendas sobem e caem?", "expect": ["Natal"]},
    {"id": "accessibility_en", "language": "en", "first": "My shop has a wheelchair ramp at the entrance, it's important to me.",
     "last": "What accessibility feature did I mention about my shop?", "expect": ["wheelchair", "ramp"]},
    {"id": "loyalty_program_pt", "language": "pt", "first": "Tenho um programa de fidelidade: a cada 10 compras, a 11ª é grátis.",
     "last": "Como funciona o programa de fidelidade que eu descrevi?", "expect": ["10", "grátis"]},
]


def judge_llm():
    from app.infra.llm.anthropic_provider import AnthropicProvider
    llm = AnthropicProvider()
    llm.model = "claude-haiku-5-5"
    llm.thinking = "omit"
    llm.input_usd_per_mtok, llm.output_usd_per_mtok = 0.8, 4.0
    return llm


def judge_recall(llm, first_message: str, question: str, answer: str) -> dict:
    """True only if the answer demonstrates the specific fact from ``first_message`` — a
    coincidental mention or a generic non-answer does not count, and a correct paraphrase does."""
    system = ("You check whether an assistant's answer demonstrates it remembers a specific fact a "
              "customer stated earlier in a long conversation. Judge ONLY the fact the question asks "
              "about. A correct paraphrase counts as remembering; a vague, generic or missing answer, "
              "or one that just repeats the question, does not. Return JSON: {\"remembered\": boolean, "
              "\"reason\": string (<=15 words)}.")
    payload = {"earlier_message": first_message, "question_now": question, "assistant_answer": answer}
    response = llm.chat([{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                        json_schema={"type": "object", "properties": {"remembered": {"type": "boolean"}, "reason": {"type": "string"}},
                                    "required": ["remembered", "reason"]},
                        max_tokens=80, purpose="memory_judge")
    data = json.loads(response.get("content") or "{}")
    data["usage"] = response.get("usage", {})
    return data


def run(mode: str, *, judge: bool = False) -> dict:
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
        def login() -> dict:
            token = client.post("/api/auth/demo-login", json={"user_id": "cliente1988", "pin": "1988"}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        judge_model = judge_llm() if judge else None
        judge_usage = {"calls": 0, "cost_usd": 0.0}
        for conv in CONVERSATIONS:
            headers = login()  # a run takes ~1h across 30 conversations: re-login each one so the demo token never expires mid-run
            session = f"mem-{mode}-{conv['id']}"
            fillers = FILLERS_PT if conv["language"] == "pt" else FILLERS_EN
            for text in [conv["first"], *fillers]:
                client.post("/api/chat", json={"message": text, "user_id": "cliente1988", "session_id": session}, headers=headers)
            final = client.post("/api/chat", json={"message": conv["last"], "user_id": "cliente1988", "session_id": session},
                                headers=headers).json()
            answer = final.get("answer", "")
            recalled = [fact for fact in conv["expect"] if fact.casefold() in answer.casefold()]
            usage = final.get("model_usage") or {}
            row = {"id": conv["id"], "recalled_all": len(recalled) == len(conv["expect"]), "recalled": recalled,
                   "expected": conv["expect"], "answer": answer[:400], "memory": final.get("memory"),
                   "final_turn_prompt_tokens": usage.get("prompt_tokens"), "final_turn_cost_usd": usage.get("cost_usd")}
            if judge_model is not None:
                try:
                    verdict = judge_recall(judge_model, conv["first"], conv["last"], answer)
                    row["judge_remembered"] = verdict.get("remembered")
                    row["judge_reason"] = verdict.get("reason")
                    judge_usage["calls"] += 1
                    judge_usage["cost_usd"] += (verdict.get("usage") or {}).get("cost_usd") or 0.0
                except Exception as exc:  # noqa: BLE001 - a judge failure is recorded, not fatal
                    row["judge_error"] = type(exc).__name__
            out.append(row)
            print(f"  [{mode}] {conv['id']:18s} recalled={recalled} judge={row.get('judge_remembered')} memory={final.get('memory')}", flush=True)
    n = len(out)
    result = {"conversations": out, "recall_rate": round(sum(r["recalled_all"] for r in out) / n, 4),
              "mean_final_prompt_tokens": round(sum(r["final_turn_prompt_tokens"] or 0 for r in out) / n, 1),
              "summary_calls": summary_usage}
    if judge:
        result["judge_recall_rate"] = round(sum(1 for r in out if r.get("judge_remembered")) / n, 4)
        result["judge_usage"] = judge_usage
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True)
    parser.add_argument("--judge", action="store_true", help="also score with an LLM judge (claude-haiku-5-5)")
    parser.add_argument("--modes", default="on,off", help="e.g. 'on' to re-run only the memory-on pass")
    args = parser.parse_args()
    os.environ.setdefault("KNOWLEDGE_LIVE_READ", "false")
    report = {"date": date.today().isoformat(),
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
              "conversations": len(CONVERSATIONS), "turns_per_conversation": 1 + len(FILLERS_PT) + 1,
              "settings": {k: os.getenv(k) for k in ("SESSION_SUMMARY_AFTER_MESSAGES", "SESSION_MEMORY_RECENT_MESSAGES")}}
    for mode in args.modes.split(","):
        print(f"== SESSION_MEMORY={mode}", flush=True)
        report[mode] = run(mode, judge=args.judge)
    on = [r["memory"] for r in report.get("on", {}).get("conversations", []) if (r.get("memory") or {}).get("memory_used")]
    if on:
        report["context_compression"] = {
            "mean_chars_replaced": round(sum(m["chars_replaced"] for m in on) / len(on), 1),
            "mean_memory_note_chars": round(sum(m["memory_chars"] for m in on) / len(on), 1)}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("on", "off")} | {
        f"recall_{m}": report[m]["recall_rate"] for m in report if m in ("on", "off")}
    if args.judge:
        summary |= {f"judge_recall_{m}": report[m]["judge_recall_rate"] for m in report if m in ("on", "off")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
