"""Telegram Bot API channel for human operators.

A handoff sends a card (protocol, priority, reason, LLM summary without sensitive data) with
inline buttons Claim / Reply / Resolve to the operators' chat. Operators reply to the card
(or use /r <protocol> <text>), resolve with /resolve <protocol> <summary> and hand back to
the AI with /ai <protocol> <instruction>. Updates are received by long polling (getUpdates),
so no public URL is needed. Only Telegram user ids listed in TELEGRAM_OPERATOR_IDS may act.
The token is read from the environment and never logged.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)
API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_OPERATOR_CHAT_ID", "").strip())


def authorized_operator_ids() -> set[int]:
    raw = os.getenv("TELEGRAM_OPERATOR_IDS", "")
    return {int(x) for x in re.findall(r"-?\d+", raw)}


class TelegramClient:
    """Minimal Bot API client. ``post`` is injectable so tests never touch the network."""

    def __init__(self, token: str | None = None, *, post: Callable[..., Any] | None = None, timeout: float = 10.0):
        self._token = (token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self._post = post or requests.post
        self.timeout = timeout

    def __repr__(self) -> str:  # never expose the token
        return "TelegramClient()"

    def call(self, method: str, payload: dict, *, timeout: float | None = None) -> Any:
        if not self._token:
            raise TelegramError("telegram_not_configured")
        try:
            response = self._post(f"{API}/bot{self._token}/{method}", json=payload, timeout=timeout or self.timeout)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TelegramError(f"telegram_{method}_failed:{type(exc).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"telegram_{method}_error:{data.get('error_code')}")
        return data.get("result")

    def send_message(self, chat_id: str | int, text: str, *, reply_markup: dict | None = None,
                     reply_to: int | None = None) -> dict:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return self.call("sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]})

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        payload = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout + 10) or []


PRIORITY = {"critical": "🔴 CRÍTICA", "high": "🟠 ALTA", "normal": "🟢 normal"}


def ticket_card(ticket: dict, summary: str) -> tuple[str, dict]:
    protocol = ticket["protocol"]
    text = (f"Novo atendimento {protocol}\n"
            f"Prioridade: {PRIORITY.get(ticket.get('severity'), ticket.get('severity'))}\n"
            f"Motivo: {ticket.get('reason')}\n"
            f"Idioma: {ticket.get('language')}\n\n"
            f"Resumo: {summary}\n\n"
            f"Responda a esta mensagem para falar com o cliente, ou use /r {protocol} <texto>. "
            f"/resolve {protocol} <resumo> encerra; /ai {protocol} <instrução> devolve para a IA.")
    keyboard = {"inline_keyboard": [[
        {"text": "Assumir", "callback_data": f"claim:{protocol}"},
        {"text": "Responder", "callback_data": f"reply:{protocol}"},
        {"text": "Resolver", "callback_data": f"resolve:{protocol}"},
    ]]}
    return text, keyboard


COMMAND = re.compile(r"^/(r|resolve|ai)(?:@\w+)?\s+(GET-\d{8}-[0-9A-F]{6})\s+(.+)$", re.IGNORECASE | re.DOTALL)


def parse_update(update: dict, lookup_protocol: Callable[[int], str | None]) -> dict | None:
    """Translate one Telegram update into an operator action, or None when irrelevant.

    Returns {"action": claim|reply|resolve|return_to_ai|reply_prompt, "protocol", "text",
    "operator_tg_id", "operator_name", "callback_id"?}.
    """
    if "callback_query" in update:
        cq = update["callback_query"]
        kind, _, protocol = str(cq.get("data", "")).partition(":")
        user = cq.get("from", {})
        action = {"claim": "claim", "resolve": "resolve_prompt", "reply": "reply_prompt"}.get(kind)
        if not action:
            return None
        return {"action": action, "protocol": protocol.upper(), "text": "", "operator_tg_id": user.get("id"),
                "operator_name": user.get("username") or user.get("first_name") or str(user.get("id")),
                "callback_id": cq.get("id")}
    message = update.get("message") or {}
    text = str(message.get("text") or "").strip()
    user = message.get("from", {})
    if not text or user.get("is_bot"):
        return None
    base = {"operator_tg_id": user.get("id"),
            "operator_name": user.get("username") or user.get("first_name") or str(user.get("id"))}
    match = COMMAND.match(text)
    if match:
        verb, protocol, body = match.groups()
        return {**base, "action": {"r": "reply", "resolve": "resolve", "ai": "return_to_ai"}[verb.lower()],
                "protocol": protocol.upper(), "text": body.strip()}
    replied = (message.get("reply_to_message") or {}).get("message_id")
    if replied:
        protocol = lookup_protocol(int(replied))
        if protocol:
            return {**base, "action": "reply", "protocol": protocol, "text": text}
    return None


def dumps_safe(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)[:500]
