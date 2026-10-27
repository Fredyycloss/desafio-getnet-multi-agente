class RouterAgent:
    name = "router_agent"
    def route(self, message: str) -> str:
        text = message.lower()
        support = ("maquininha", "máquina", "maquina", "internet", "wifi", "wi-fi", "conectar", "conexão", "conexao", "recus", "declin", "transação", "transacao", "depósito", "deposito", "receb", "saldo", "vendas de ontem", "payment status", "deposit", "payout", "sales from yesterday", "terminal", "card machine", "declined", "decline error", "connect to the internet", "wont connect", "won't connect")
        general = ("clima", "tempo amanhã", "câmbio", "cambio", "euro", "cotação", "cotacao", "notícia", "noticia", "weather", "exchange rate", "forecast")
        if any(term in text for term in support):
            return "customer_support"
        if any(term in text for term in general):
            return "general_question"
        return "knowledge"
