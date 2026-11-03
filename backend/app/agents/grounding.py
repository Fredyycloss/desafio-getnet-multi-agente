"""Deterministic check that values in an answer exist in tool observations.

Used by the Critic before the model review: every identifier, date, amount and
transaction status that a generated answer states must be traceable to the
structured data the specialists actually observed. A mismatch rejects the
answer without spending a model call.

Limitations (documented, intentional): dates written out in words ("3 de
novembro") and small integers (< 10, typically counts or list markers) are not
checked; terminal online/offline wording is left to the model critic because
advice such as "when it is online again" is not a status claim.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

ID_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+)+\b")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")  # also inside ISO timestamps (…T00:36:38)
BR_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
NUMBER_RE = re.compile(r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,4})?(?![\w])|(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])")

# Transaction/settlement statuses whose wording is distinctive enough to check.
STATUS_TERMS = {
    "approved": ("approved", "aprovad"),
    "declined": ("declined", "recusad"),
    "scheduled": ("scheduled", "agendad"),
    "settled": ("settled", "liquidad"),
    "pending": ("pending", "pendente"),
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _parse_number(token: str) -> tuple[float, int] | None:
    """Parse '1.234,56', '1,234.56', '242.75', '242,75' -> (value, decimals)."""
    token = token.strip()
    if "." in token and "," in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        token = token.replace(thousands, "").replace(decimal_sep, ".")
    elif "," in token:
        head, _, tail = token.rpartition(",")
        token = token.replace(",", "") if len(tail) == 3 and head.isdigit() and len(head) <= 3 else token.replace(",", ".")
    elif token.count(".") > 1:
        token = token.replace(".", "")
    try:
        value = float(token)
    except ValueError:
        return None
    decimals = len(token.split(".", 1)[1]) if "." in token else 0
    return value, decimals


class Facts:
    def __init__(self) -> None:
        self.numbers: set[float] = set()
        self.dates: set[date] = set()
        self.identifiers: set[str] = set()
        self.statuses: set[str] = set()

    def add_text(self, text: str) -> None:
        for match in ID_RE.findall(text):
            self.identifiers.add(match.upper())
        for y, m, d in ISO_DATE_RE.findall(text):
            try:
                self.dates.add(date(int(y), int(m), int(d)))
            except ValueError:
                continue
            # "dia 15", "novembro de 2026": date parts may be stated on their own.
            self.numbers.update({float(y), float(m), float(d)})
        stripped = ISO_DATE_RE.sub(" ", ID_RE.sub(" ", text))
        for token in NUMBER_RE.findall(stripped):
            parsed = _parse_number(token)
            if parsed:
                self.numbers.add(parsed[0])
        folded = _fold(text)
        for status, forms in STATUS_TERMS.items():
            if status in folded or any(form in folded for form in forms):
                self.statuses.add(status)

    def add(self, value) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            self.numbers.add(float(value))
        elif isinstance(value, str):
            self.add_text(value)
        elif isinstance(value, dict):
            for item in value.values():
                self.add(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.add(item)


def collect_facts(observations: list) -> Facts:
    facts = Facts()
    facts.add(observations)
    return facts


def _number_supported(value: float, decimals: int, facts: Facts) -> bool:
    # An answer may round an observed value (e.g. 5.4321 -> 5.43, 23.8 -> 24).
    tolerance = 0.5 * (10 ** -decimals) + 1e-9
    return any(abs(value - observed) <= tolerance for observed in facts.numbers)


def find_unsupported(answer: str, observations: list) -> list[str]:
    """Return the values stated in ``answer`` that no observation supports."""
    facts = collect_facts(observations)
    unsupported: list[str] = []

    for identifier in ID_RE.findall(answer):
        if identifier.upper() not in facts.identifiers:
            unsupported.append(f"id:{identifier}")

    for y, m, d in ISO_DATE_RE.findall(answer):
        try:
            stated = date(int(y), int(m), int(d))
        except ValueError:
            unsupported.append(f"date:{y}-{m}-{d}")
            continue
        if stated not in facts.dates:
            unsupported.append(f"date:{stated.isoformat()}")

    text = ISO_DATE_RE.sub(" ", ID_RE.sub(" ", answer))
    for d, m, y in BR_DATE_RE.findall(text):
        day, month = int(d), int(m)
        year = int(y) + 2000 if y and len(y) == 2 else (int(y) if y else None)
        if not any(obs.day == day and obs.month == month and (year is None or obs.year == year) for obs in facts.dates):
            unsupported.append(f"date:{d}/{m}" + (f"/{y}" if y else ""))
    text = BR_DATE_RE.sub(" ", text)

    for token in NUMBER_RE.findall(text):
        parsed = _parse_number(token)
        if not parsed:
            continue
        value, decimals = parsed
        if decimals == 0 and value < 10:
            continue
        if not _number_supported(value, decimals, facts):
            unsupported.append(f"value:{token}")

    folded = _fold(answer)
    for status, forms in STATUS_TERMS.items():
        if any(form in folded for form in forms) and status not in facts.statuses:
            unsupported.append(f"status:{status}")

    return list(dict.fromkeys(unsupported))
