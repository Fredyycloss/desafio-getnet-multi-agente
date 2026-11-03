"""Deterministic Portuguese/English language detection for the demo assistant.

The detector intentionally has no external API dependency. It prioritizes an
explicit response-language request, then language-specific words/phrases, and
uses prior user turns only when the current message is genuinely ambiguous.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


PT_CUES = set(normalize("""
    você voces voceis vocês eu meu minha meus minhas nosso nossa o a os as um uma uns umas
    de da do das dos no na nos nas num numa para por pelo pela pelos pelas com sem sobre
    que qual quais quem quando quanto onde porque porquê como fazer faz preciso quero queria
    pode posso poderia tem tenho tinha esta está estão estavam foi foram sera será sao são
    nao não sim dinheiro recebimento recebíveis receber recebo venda vendas maquininha maquina
    máquina cartao cartão taxa taxas tarifa tarifas aluguel adesao adesão pix pagamento pagamentos
    conexão conexao conectar funciona funcionando continuar continua continuao ainda isso essa
    esse ela ele atendimento atendente suporte explosao explosão explodiu explodindo fumaca fumaça
    fogo queimado faísca faisca choque bateria estufada
""").split())
EN_CUES = set("""
    you your yours i me my mine we our they them this that these those what when where who why how
    is are was were can could would should do does did have has had please thanks thank hello hi
    need want looking tell explain compare difference between about for from with without the a an
    machine terminal device payment card sales money deposit received receive payout settlement
    internet connection connect disconnected offline works working issue problem help support
    price fee fees tax taxes rental rent cost how much available eligibility features website link
    exploded explosion smoke smoking fire flames burning smell sparks shock battery swollen
""".split())

PT_PHRASES = tuple(normalize(x) for x in (
    "por favor", "o que", "como faço", "como faco", "minha maquininha", "nao funciona",
    "não funciona", "e se", "meu dinheiro", "em portugues", "em português", "responda em portugues",
    "quero falar com", "quanto custa", "qual e a taxa", "qual é a taxa", "minha maquina",
    "maquininha explodiu", "esta saindo fumaca", "está saindo fumaça",
))
EN_PHRASES = tuple(normalize(x) for x in (
    "please", "what is", "what's", "how do", "how can", "my card machine", "doesn't work",
    "does not work", "what if", "in english", "answer in english", "respond in english",
    "speak to a human", "how much does", "what is the fee", "my machine exploded",
    "there is smoke", "smells like burning", "caught fire",
))


def _score(text: str) -> tuple[int, int]:
    normalized = normalize(text)
    words = re.findall(r"[a-z0-9]+", normalized)
    counts = Counter(words)
    pt = sum(2 if word not in {"a", "o", "e", "de", "do", "da", "que", "no", "na"} else 1 for word in counts if word in PT_CUES)
    en = sum(2 if word not in {"a", "an", "the", "is", "do", "to", "in", "on", "and", "or"} else 1 for word in counts if word in EN_CUES)
    pt += 4 * sum(1 for phrase in PT_PHRASES if phrase in normalized)
    en += 4 * sum(1 for phrase in EN_PHRASES if phrase in normalized)
    # Accented Portuguese characters provide useful evidence for short messages.
    if any(ch in (text or "").lower() for ch in "ãõçáéíóúàâêô"): pt += 3
    return pt, en


def _explicit_language_request(message: str) -> str | None:
    text = normalize(message)
    if re.search(r"\b(in portuguese|in brazilian portuguese|em portugues|em portugues brasileiro|responda em portugues|responda em pt-br)\b", text):
        return "pt"
    if re.search(r"\b(in english|answer in english|respond in english|em ingles|responda em ingles)\b", text):
        return "en"
    return None


def detect_language(message: str, history: Iterable[dict] | None = None) -> str:
    """Return `pt` or `en`, inheriting the last clear user language for follow-ups."""
    requested = _explicit_language_request(message)
    if requested:
        return requested
    pt, en = _score(message)
    # A single unique, language-bearing cue should beat the neutral defaults.
    if pt >= 2 and pt > en:
        return "pt"
    if en >= 2 and en > pt:
        return "en"
    if pt != en and max(pt, en) >= 3:
        return "pt" if pt > en else "en"
    if history:
        for item in reversed(list(history)):
            if item.get("role") != "user" or not item.get("content", "").strip():
                continue
            prior_pt, prior_en = _score(item["content"])
            if prior_pt != prior_en and max(prior_pt, prior_en) >= 2:
                return "pt" if prior_pt > prior_en else "en"
            explicit = _explicit_language_request(item["content"])
            if explicit:
                return explicit
    # Brazilian-first product demo default for neutral text.
    return "pt"
