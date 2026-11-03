from __future__ import annotations
import re

# Block only when a likely secret value is being disclosed; asking how to reset a password is allowed.
SECRET_VALUE_PATTERNS = [
    r"\b(?:senha|password|token|otp|cvv|cvc)\s*(?:é|e|is|:|=)\s*\S+",
    r"\b(?:my|minha|meu)\s+(?:password|senha|token|otp)\s*(?:is|é|e|:|=)\s*\S+",
    r"\b(?:one[- ]time code|c[oó]digo de autentica[cç][aã]o)\s*(?:is|é|:|=)\s*\S+",
    r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
]
HUMAN_PATTERNS = [
    r"\b(atendimento humano|atendente|quero (?:falar|conversar) com (?:uma? )?(?:pessoa|humano|funcion[aá]rio|atendente)|preciso de (?:um )?(?:atendente|funcion[aá]rio)|falar com (?:uma? )?(?:pessoa|humano|atendente)|transfira(?:-me)? para (?:algu[eé]m|uma pessoa|um atendente)|chame (?:uma pessoa|um atendente)|n[aã]o quero falar com (?:um )?rob[oô])\b",
    r"\b(?:human agent|human support|talk to (?:a )?(?:person|human|agent)|speak to (?:a )?(?:person|human|agent)|real person|transfer me to (?:someone|a person|an agent)|i (?:want|need) (?:to talk to )?(?:a )?(?:person|human|agent)|i (?:do not|don't|dont) want (?:to talk to|a) (?:a )?(?:bot|robot))\b",
]
MESSAGES = {
    "pt": "Por segurança, não compartilhe senhas, tokens, códigos de autenticação nem números completos de cartão. Para redefinir credenciais, use o canal oficial autenticado da Getnet.",
    "en": "For your security, do not share passwords, tokens, authentication codes, or full card numbers. Use an authenticated official Getnet channel to reset credentials.",
}

def inspect_message(message: str, language: str = "pt") -> dict:
    if any(re.search(pattern, message, re.I) for pattern in SECRET_VALUE_PATTERNS):
        return {"blocked": True, "reason": "sensitive_secret_disclosure", "message": MESSAGES.get(language, MESSAGES["pt"])}
    if any(re.search(pattern, message, re.I) for pattern in HUMAN_PATTERNS):
        return {"blocked": False, "handoff": True, "reason": "human_requested"}
    return {"blocked": False, "handoff": False, "reason": None}
