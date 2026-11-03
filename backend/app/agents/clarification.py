from __future__ import annotations

import unicodedata


TOPIC_OPTIONS = {
    "pt": [
        {"id": "terminal_support", "label": "Maquininha, conexão ou falha"},
        {"id": "sales_payments", "label": "Vendas, pagamentos ou recebimentos"},
        {"id": "products_fees", "label": "Produtos, taxas ou serviços Getnet"},
        {"id": "human_support", "label": "Falar com atendente humano"},
    ],
    "en": [
        {"id": "terminal_support", "label": "Terminal, connection, or technical issue"},
        {"id": "sales_payments", "label": "Sales, payments, or settlements"},
        {"id": "products_fees", "label": "Getnet products, fees, or services"},
        {"id": "human_support", "label": "Speak with a human attendant"},
    ],
}

CONTEXT_OPTIONS = {
    "pt": [
        {"id": "literal_hazard", "label": "Há um risco físico real acontecendo agora"},
        {"id": "figurative_expression", "label": "É uma expressão figurada ou um desabafo"},
        {"id": "getnet_topic", "label": "Quero ajuda com um assunto Getnet"},
        {"id": "human_support", "label": "Falar com atendente humano"},
    ],
    "en": [
        {"id": "literal_hazard", "label": "There is a real physical hazard happening now"},
        {"id": "figurative_expression", "label": "It is a figurative expression or frustration"},
        {"id": "getnet_topic", "label": "I need help with a Getnet topic"},
        {"id": "human_support", "label": "Speak with a human attendant"},
    ],
}


TERMINAL_OPTIONS = {
    "pt": [
        {"id": "terminal_connection", "label": "Problemas de conexão"},
        {"id": "terminal_sales", "label": "Problemas para realizar vendas"},
        {"id": "terminal_defect", "label": "Defeito ou funcionamento da maquininha"},
        {"id": "sales_payments", "label": "Dúvidas sobre pagamentos"},
        {"id": "human_support", "label": "Quero falar com atendimento humano"},
    ],
    "en": [
        {"id": "terminal_connection", "label": "Connection problems"},
        {"id": "terminal_sales", "label": "Unable to accept sales"},
        {"id": "terminal_defect", "label": "Terminal defect or operation"},
        {"id": "sales_payments", "label": "Payment questions"},
        {"id": "human_support", "label": "I want human support"},
    ],
}

PAYMENT_OPTIONS = {
    "pt": [
        {"id": "payment_status", "label": "Situação de uma venda ou pagamento"},
        {"id": "settlement_timing", "label": "Prazo para receber uma venda"},
        {"id": "declined_transaction", "label": "Venda recusada"},
        {"id": "products_fees", "label": "Produtos, taxas ou serviços Getnet"},
        {"id": "human_support", "label": "Quero falar com atendimento humano"},
    ],
    "en": [
        {"id": "payment_status", "label": "Sale or payment status"},
        {"id": "settlement_timing", "label": "When a sale will be settled"},
        {"id": "declined_transaction", "label": "Declined transaction"},
        {"id": "products_fees", "label": "Getnet products, fees, or services"},
        {"id": "human_support", "label": "I want human support"},
    ],
}


def _normalise(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


def clarification_kind(language: str, *, contextual: bool, intent: str = "", message: str = "") -> str:
    text = _normalise(f"{intent} {message}")
    if contextual and any(term in text for term in (
        "bomba", "bomb", "fumaca", "smoke", "cheiro de queimado", "burning smell",
        "queimando", "burning", "choque", "shock", "eletric", "electric", "explod",
        "machucar", "hurt", "risco fisico", "physical danger",
    )):
        return "contextual"
    if any(term in text for term in ("payment", "pagamento", "receb", "settlement", "transacao", "venda", "sales")):
        return "sales_payments"
    if any(term in text for term in ("terminal", "maquina", "maquininha", "conexao", "connection", "tecnico", "technical", "defeito")):
        return "terminal_support"
    if contextual:
        return "contextual"
    return "general_topics"


def clarification_result(
    language: str,
    *,
    contextual: bool = False,
    unsupported: bool = False,
    safety: bool = False,
    intent: str = "",
    message: str = "",
) -> dict:
    """Topic menu. ``safety=True`` (model saw possible danger without a deterministic
    hazard) guarantees a "real physical risk" option first and the human option."""
    language = "en" if language == "en" else "pt"
    kind = clarification_kind(language, contextual=contextual or safety, intent=intent, message=message)
    if kind == "contextual":
        options = CONTEXT_OPTIONS[language]
    elif kind == "terminal_support":
        options = TERMINAL_OPTIONS[language]
    elif kind == "sales_payments":
        options = PAYMENT_OPTIONS[language]
    else:
        options = TOPIC_OPTIONS[language]
    if safety and not any(item["id"] == "literal_hazard" for item in options):
        hazard = next(item for item in CONTEXT_OPTIONS[language] if item["id"] == "literal_hazard")
        options = [hazard, *[item for item in options if item["id"] != "human_support"][:3],
                   next(item for item in options if item["id"] == "human_support")]
        kind = f"safety_{kind}"
    contextual = contextual or safety
    if language == "en":
        intro = (
            "I could not find enough supported information to answer that safely. Which topic should I check?"
            if unsupported else
            "I want to make sure I understood. Which option best describes what you mean?"
            if contextual else
            "Which topic would you like help with?"
        )
        footer = "Reply with an option name or number. Choosing human support may create a simulated ticket; no live attendant is connected."
        heading = "Choose a topic:"
    else:
        intro = (
            "Não encontrei informação suficiente na base para responder com segurança. Qual assunto você quer que eu verifique?"
            if unsupported else
            "Quero confirmar se entendi. Qual opção descreve melhor o que você quis dizer?"
            if contextual else
            "Qual assunto você gostaria de tratar?"
        )
        footer = "Responda com o nome ou número da opção. A escolha por atendimento humano pode criar um protocolo simulado; nenhum atendente real está conectado."
        heading = "Escolha uma opção:"
    answer = intro + "\n\n" + heading + "\n" + "\n".join(
        f"{index}. {item['label']}" for index, item in enumerate(options, start=1)
    ) + "\n\n" + footer
    return {
        "answer": answer,
        "confidence": 0.75,
        "sources": [],
        "handoff": False,
        "clarification_options": options,
        "clarification_kind": kind,
    }


def selected_topic_result(language: str, topic_id: str) -> dict:
    language = "en" if language == "en" else "pt"
    prompts = {
        "pt": {
            "terminal_support": "Conte o que acontece com a maquininha ou conexão e, se souber, informe o modelo e a mensagem de erro.",
            "terminal_connection": "Conte se a maquininha não encontra a rede, cai durante o uso ou mostra algum código de erro.",
            "terminal_sales": "Conte o que acontece quando tenta realizar uma venda e, se aparecer, informe a mensagem de erro.",
            "terminal_defect": "Descreva o defeito ou comportamento da maquininha e informe o modelo, se souber.",
            "sales_payments": "Sua dúvida é sobre uma venda, pagamento, recebimento ou prazo? Conte os detalhes sem incluir dados de cartão ou senhas.",
            "payment_status": "Informe a data e o valor aproximado da venda, sem enviar dados de cartão ou senha.",
            "settlement_timing": "Qual tipo de venda ou prazo de recebimento você quer consultar? Não envie dados do cartão.",
            "declined_transaction": "Conte quando a venda foi recusada e a mensagem exibida, sem compartilhar dados do cartão.",
            "products_fees": "Qual produto, serviço ou taxa da Getnet você quer consultar?",
            "getnet_topic": "Qual produto, serviço ou situação da Getnet você quer entender melhor?",
            "figurative_expression": "Entendi. Qual ajuda você precisa com a Getnet ou com a situação que descreveu?",
        },
        "en": {
            "terminal_support": "Describe what is happening with the terminal or connection and, if known, include the model and error message.",
            "terminal_connection": "Tell me whether the terminal cannot find the network, disconnects during use, or shows an error code.",
            "terminal_sales": "Describe what happens when you try to make a sale and include any displayed error message.",
            "terminal_defect": "Describe the defect or unexpected terminal behavior and include its model if known.",
            "sales_payments": "Is your question about a sale, payment, settlement, or timing? Share details without card data or passwords.",
            "payment_status": "Share the approximate date and amount of the sale, without card data or passwords.",
            "settlement_timing": "Which sale type or settlement time would you like to check? Do not share card details.",
            "declined_transaction": "Tell me when the transaction was declined and what message appeared, without card details.",
            "products_fees": "Which Getnet product, service, or fee would you like to check?",
            "getnet_topic": "Which Getnet product, service, or situation would you like help understanding?",
            "figurative_expression": "Understood. What help do you need with Getnet or the situation you described?",
        },
    }
    return {
        "answer": prompts[language].get(topic_id, prompts[language]["getnet_topic"]),
        "confidence": 0.9,
        "sources": [],
        "handoff": False,
        "clarification_topic": topic_id,
    }
