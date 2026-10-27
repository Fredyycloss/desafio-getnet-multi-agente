from .support_tools import lookup_payment_status, troubleshoot_terminal

class CustomerSupportAgent:
    name = "customer_support_agent"
    def run(self, message: str, user_id: str) -> dict:
        lowered = message.lower()
        if any(word in lowered for word in ("receb", "depósit", "deposit", "vendas de ontem", "sales from yesterday", "payout", "saldo", "payment status", "money from yesterday")):
            result = lookup_payment_status(user_id, "ontem" if "ontem" in lowered or "yesterday" in lowered else "período mencionado")
            answer = result["message"]
            trace = ["customer_support_agent", "tool:lookup_payment_status"]
        else:
            result = troubleshoot_terminal(message)
            answer = "Vamos começar por estes passos:\n\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(result["steps"]))
            trace = ["customer_support_agent", "tool:troubleshoot_terminal"]
        return {"answer": answer, "confidence": 0.82, "sources": [{"title": "Orientações de suporte demonstrativas", "url": "https://www.getnet.net/"}], "trace": trace, "tool_result": result}
