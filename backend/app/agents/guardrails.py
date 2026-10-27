import re

SENSITIVE_PATTERNS = [
    r"\b(senha|password|token|código de autenticação|codigo de autenticacao)\b",
    r"\b(número completo do cartão|numero completo do cartao|cvv|cvc)\b",
]
HUMAN_PATTERNS = [r"\b(atendente|atendimento humano|falar com uma pessoa|reclamação formal|reclamacao formal)\b"]


def inspect_message(message: str) -> dict:
    lowered = message.lower()
    if any(re.search(p, lowered) for p in SENSITIVE_PATTERNS):
        return {"blocked": True, "reason": "sensitive_data", "message": "Por segurança, não envie senhas, tokens, códigos de autenticação nem dados completos de cartão por aqui. Para assuntos da sua conta, use um canal oficial autenticado da Getnet."}
    if any(re.search(p, lowered) for p in HUMAN_PATTERNS):
        return {"blocked": False, "handoff": True, "reason": "human_requested"}
    return {"blocked": False, "handoff": False, "reason": None}
