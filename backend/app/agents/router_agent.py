from __future__ import annotations
import re
from ..language import normalize

FOLLOW_UP_PATTERNS = (
    r"^(and|so|but|what about|what if|how about|then|it|that|this|if it|if that)\b",
    r"^(e se|e quando|e depois|mas e|nesse caso|isso|ele|ela|ainda|continua|se continuar|e agora)\b",
)

class RouterAgent:
    name = "router_agent"

    @staticmethod
    def is_follow_up(message: str) -> bool:
        text = normalize(message).strip()
        words = text.split()
        if any(re.search(pattern, text) for pattern in FOLLOW_UP_PATTERNS):
            return True
        # Short pronoun-led turns usually depend on the previous turn.
        return len(words) <= 5 and any(w in words for w in ("it", "that", "this", "isso", "essa", "esse", "ele", "ela"))

    def contextual_query(self, message: str, history: list[dict] | None = None) -> str:
        history = history or []
        # A new message after an options menu can be a topic change, not an option
        # selection. The Supervisor resolves actual selections before routing.
        for item in reversed(history):
            if item.get("role") == "assistant":
                if isinstance(item.get("clarification_options"), list):
                    return message
                break
        if not history or not self.is_follow_up(message):
            return message
        previous_user = next((item.get("content", "") for item in reversed(history) if item.get("role") == "user"), "")
        if not previous_user:
            return message
        # Include topic and follow-up without turning the entire chat into the query.
        return f"{previous_user}\nFollow-up: {message}"

    def route(self, message: str, history: list[dict] | None = None) -> str:
        text = normalize(self.contextual_query(message, history))
        # Specific troubleshooting is handled before broad payment vocabulary.
        troubleshooting = (
            "maquininha", "maquina", "terminal", "card machine", "payment terminal", "pos device",
            "internet", "wifi", "wi-fi", "conectar", "conexao", "connect", "connection", "signal",
            "sinal", "recus", "declin", "transaction declined", "payment declined", "transacao recusada",
            "error code", "erro na", "nao funciona", "doesnt work", "does not work", "won't work",
            "wont connect", "still not working", "ainda nao funciona", "continuar sem funcionar",
        )
        if any(term in text for term in troubleshooting):
            return "customer_support"

        personal_payment = (
            "when will my", "when will i receive", "money from yesterday", "sales from yesterday",
            "payment status", "payout status", "my balance", "my payout", "deposit date",
            "quando recebo", "quando vou receber", "vendas de ontem", "meu saldo", "meu deposito",
            "meu recebimento", "quando cai", "cadê meu dinheiro", "cadê o dinheiro", "status do pagamento",
        )
        if any(term in text for term in personal_payment):
            return "customer_support"

        live_data = ("weather", "forecast", "exchange rate", "euro rate", "stock price", "news today", "clima", "previsao do tempo", "previsão do tempo", "cotacao do euro", "cambio hoje", "noticias de hoje")
        if any(term in text for term in live_data):
            return "general_question"

        smalltalk = (
            "hi", "hello", "hello there", "hey", "good morning", "good afternoon", "good evening",
            "thanks", "thank you", "oi", "ola", "bom dia", "boa tarde", "boa noite", "obrigado",
            "obrigada", "como voce pode me ajudar", "como posso te ajudar", "how can you help me",
            "what can you help me with",
        )
        if text.strip(" .!?\t") in smalltalk:
            return "smalltalk"

        # Broad general-knowledge questions go to public search when they are
        # not anchored to Getnet or the payments domain. Product questions stay
        # grounded in the official Getnet corpus.
        general_starts = (
            "what is ", "who is ", "where is ", "why is ", "tell me about ", "explain ",
            "what are ", "who are ", "qual e ", "o que e ", "quem e ", "onde fica ",
            "por que ", "me fale sobre ", "explique ",
        )
        payment_context = (
            "getnet", "get lite", "get smart", "get classica", "get classic", "maquininha", "maquina",
            "terminal", "card machine", "payment", "pagamento", "card", "cartao", "pix", "payout",
            "settlement", "recebimento", "recebiveis", "payment link", "link de pagamento", "antecipacao",
            "checkout", "taxa", "fees", "rates", "get tap", "pos device",
        )
        if text.startswith(general_starts) and not any(term in text for term in payment_context):
            return "general_question"

        # Requests about features, eligibility, product differences and payment methods
        # remain in the grounded knowledge route, not the demo account tool.
        return "knowledge"
