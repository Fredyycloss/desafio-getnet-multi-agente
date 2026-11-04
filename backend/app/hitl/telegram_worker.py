"""Telegram long-polling worker (single instance): python -m app.hitl.telegram_worker

Receives operator actions from the operators' chat and applies them through HITLService.
Unauthorized Telegram users are refused and audited. A heartbeat marks the channel live so
the API can report real_agent_connected=true. Without a token it idles and says so.
"""
from __future__ import annotations

import logging
import os
import time

from ..infra.database import Database
from . import operators as ops
from .service import HITLService
from .telegram import TelegramClient, TelegramError, authorized_operator_ids, parse_update, telegram_configured

logger = logging.getLogger("telegram_worker")


def handle(update: dict, hitl: HITLService, client: TelegramClient, allowed: set[int]) -> str:
    """Apply one update. Returns an outcome label (for logs and tests)."""
    action = parse_update(update, hitl.db.protocol_for_telegram_message)
    if action is None:
        return "ignored"
    tg_id = action.get("operator_tg_id")
    operator = {"username": f"tg:{tg_id}", "display_name": action.get("operator_name") or f"tg:{tg_id}", "role": "operator"}
    chat_id = hitl.chat_id

    def say(text: str) -> None:
        try:
            if action.get("callback_id"):
                client.answer_callback(action["callback_id"], text)
            else:
                client.send_message(chat_id, text)
        except TelegramError as exc:
            logger.warning("telegram_ack_failed error=%s", exc)

    if tg_id not in allowed:
        ops.audit(hitl.db, operator["username"], "telegram", action["action"], action.get("protocol"), "unauthorized")
        say("Operador não autorizado.")
        return "unauthorized"
    protocol = action["protocol"]
    if hitl.db.get_ticket(protocol) is None:
        say(f"Protocolo {protocol} não encontrado.")
        return "not_found"
    try:
        if action["action"] == "claim":
            hitl.claim(protocol, operator, "telegram")
            say(f"{protocol} assumido por {operator['display_name']}.")
        elif action["action"] == "reply_prompt":
            say(f"Responda ao card de {protocol} (ou use /r {protocol} <texto>).")
        elif action["action"] == "resolve_prompt":
            say(f"Use /resolve {protocol} <resumo da resolução>.")
        elif action["action"] == "reply":
            ticket = hitl.db.get_ticket(protocol)
            if ticket["status"] == "queued":
                hitl.claim(protocol, operator, "telegram")  # replying implies taking the case
            hitl.reply(protocol, operator, action["text"], "telegram")
            say(f"Mensagem enviada ao cliente ({protocol}).")
        elif action["action"] == "resolve":
            hitl.resolve(protocol, operator, action["text"], "telegram")
            say(f"{protocol} resolvido.")
        elif action["action"] == "return_to_ai":
            hitl.return_to_ai(protocol, operator, action["text"], "telegram")
            say(f"{protocol} devolvido ao assistente com a instrução.")
        return action["action"]
    except ValueError as exc:
        ops.audit(hitl.db, operator["username"], "telegram", action["action"], protocol, f"rejected:{exc}")
        say(f"Não foi possível: {exc}.")
        return f"rejected:{exc}"


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db = Database()
    if not telegram_configured():
        logger.warning("telegram_not_configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_OPERATOR_CHAT_ID; idling")
        while True:
            time.sleep(300)
    client = TelegramClient()
    hitl = HITLService(db, telegram=client)
    allowed = authorized_operator_ids()
    offset = None
    logger.info("telegram_worker_started authorized_operators=%d", len(allowed))
    while True:
        ops.heartbeat(db, "telegram")
        try:
            updates = client.get_updates(offset)
        except TelegramError as exc:
            logger.warning("telegram_poll_failed error=%s", exc)
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            outcome = handle(update, hitl, client, allowed)
            logger.info("telegram_update outcome=%s", outcome)


if __name__ == "__main__":
    raise SystemExit(main())
