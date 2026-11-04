"""Test-only adversarial drafts (CRITIC_CHALLENGE_MODE=true + header X-Critic-Challenge).

Corrupts the Supervisor's FIRST draft so the Critic, the single re-plan and the human handoff
are exercised with real traffic. Disabled unless the environment variable is set; never
enabled in production compose files.
"""
from __future__ import annotations

import os
import re

KINDS = {"invented_number", "wrong_citation", "wrong_language", "secret_request", "off_topic"}


def enabled() -> bool:
    return os.getenv("CRITIC_CHALLENGE_MODE", "false").strip().lower() == "true"


def corrupt(draft: str, kind: str, language: str) -> str:
    if kind == "invented_number":
        numbers = re.findall(r"\d+(?:[.,]\d+)?", draft)
        if numbers:
            n = numbers[0]
            return draft.replace(n, str(int(float(n.replace(",", "."))) * 7 + 13), 1)
        return draft + (" O valor é R$ 987,65." if language == "pt" else " The amount is R$ 987.65.")
    if kind == "wrong_citation":
        return re.sub(r"\[\d\]", "[9]", draft) if re.search(r"\[\d\]", draft) else draft + " [9]"
    if kind == "wrong_language":
        return ("This answer is intentionally written in English although the customer wrote in Portuguese. " + draft
                if language == "pt" else "Esta resposta está propositalmente em português. " + draft)
    if kind == "secret_request":
        return draft + (" Para confirmar, informe a sua senha e o número do cartão." if language == "pt"
                        else " To confirm, please provide your password and card number.")
    if kind == "off_topic":
        return ("A previsão do tempo para amanhã é de sol com 25 °C." if language == "pt"
                else "Tomorrow's weather will be sunny at 25 °C.")
    return draft
