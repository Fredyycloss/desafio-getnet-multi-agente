"""Persistent human-support queue backed by SQLite; operators work it from the console or Telegram (app/hitl)."""
from __future__ import annotations

from ..infra.database import Database


class HumanHandoffAgent:
    name = "human_handoff_agent"

    def __init__(self, db: Database):
        self.db = db

    def create_ticket(
        self,
        *,
        user_id: str,
        message: str,
        reason: str,
        language: str = "pt",
        severity: str = "normal",
        session_id: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        return self.db.create_ticket(user_id, session_id, reason, severity, language, message, history)

    def list_tickets(self, status: str | None = None) -> list[dict]:
        return self.db.list_tickets(status)

    def get_ticket(self, protocol: str) -> dict | None:
        return self.db.get_ticket(protocol)

    def append_customer_message(self, protocol: str, message: str) -> dict | None:
        return self.db.append_ticket_message(protocol, message)
