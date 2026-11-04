"""Pending actions, confirmation, idempotent execution and audit.

Flow: an agent calls a propose_* tool -> ``propose`` validates the arguments against the
authenticated customer's own records and stores a PENDING action bound to (customer, session)
with an expiry and a one-time confirmation token -> the customer confirms ("sim" in the same
conversation, or the button, which sends the token) -> ``confirm`` executes exactly once and
returns a protocol. Nothing the model writes can execute an action: there is no execute tool,
and confirmation is checked in code against the customer's own message or token.

Idempotency: the same action (customer + kind + arguments) already executed in the last
ACTION_IDEMPOTENCY_HOURS returns the existing protocol; a second confirmation of the same
action returns the same protocol; a repeated proposal while one is pending reuses it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from .catalog import KINDS, ActionError, canonical_args

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_actions (
  action_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL, kind TEXT NOT NULL,
  args_json TEXT NOT NULL, summary TEXT NOT NULL, language TEXT NOT NULL, status TEXT NOT NULL,
  token_hash TEXT NOT NULL, idem_key TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  decided_at TEXT, protocol TEXT
);
CREATE INDEX IF NOT EXISTS ix_actions_session ON customer_actions(session_id, status);
CREATE INDEX IF NOT EXISTS ix_actions_idem ON customer_actions(idem_key, status);
CREATE TABLE IF NOT EXISTS service_requests (
  protocol TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL, kind TEXT NOT NULL,
  args_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT, user_id TEXT NOT NULL, session_id TEXT,
  event TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
"""

_YES = re.compile(r"^\s*(sim|s|confirmo|confirmar|confirma|pode|pode sim|pode confirmar|ok|isso|yes|y|confirm|go ahead|please do)\b[\s!.,]*(por favor|please|pode)?[\s!.]*$")
_NO = re.compile(r"^\s*(nao|n|cancela|cancelar|cancele|nao quero|no|cancel|stop|nevermind)\b[\s!.,]*$")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


def reply_kind(message: str) -> str | None:
    """'yes' | 'no' | None — only short, unambiguous replies count as a decision."""
    folded = _fold(message)
    if len(folded) > 40:
        return None
    if _YES.match(folded):
        return "yes"
    if _NO.match(folded):
        return "no"
    return None


def reinforced_phrase(action: dict) -> str:
    args = action["args"]
    return f"BLOQUEAR {args['terminal_id']}" if action["language"] == "pt" else f"BLOCK {args['terminal_id']}"


class ActionService:
    def __init__(self, db):
        self.db = db
        self.ttl = int(os.getenv("ACTION_CONFIRMATION_TTL_SECONDS", "600"))
        self.idem_hours = int(os.getenv("ACTION_IDEMPOTENCY_HOURS", "24"))
        with db.lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _audit(self, action_id: str | None, user_id: str, session_id: str | None, event: str, detail: str = "") -> None:
        self.db.conn.execute("INSERT INTO action_audit(action_id,user_id,session_id,event,detail,created_at) VALUES(?,?,?,?,?,?)",
                             (action_id, user_id, session_id, event, detail[:300], self._now().isoformat(timespec="seconds")))

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        d["args"] = json.loads(d.pop("args_json"))
        d.pop("token_hash", None)
        return d

    def public(self, action: dict, token: str | None = None) -> dict:
        out = {k: action[k] for k in ("action_id", "kind", "summary", "status", "expires_at", "protocol") if k in action}
        out["details"] = action.get("args", {})
        out["ttl_minutes"] = max(1, self.ttl // 60)
        out["requires_typed_confirmation"] = KINDS[action["kind"]].reinforced
        if out["requires_typed_confirmation"]:
            out["typed_confirmation_phrase"] = reinforced_phrase(action)
        if token:
            out["confirmation_token"] = token
        return out

    # ------------------------------------------------------------------ propose
    def propose(self, user_id: str, session_id: str | None, kind: str, args: dict, language: str) -> dict:
        """Validate and store a pending action. Returns an observation for the agent."""
        spec = KINDS.get(kind)
        if spec is None:
            return {"ok": False, "error": "unknown_action", "tool": f"propose_{kind}"}
        if not session_id:
            return {"ok": False, "error": "no_conversation", "tool": spec.tool["function"]["name"]}
        try:
            clean = spec.validate(self.db, user_id, args or {})
        except ActionError as exc:
            with self.db.lock:
                self._audit(None, user_id, session_id, "proposal_rejected", f"{kind}:{exc}")
                self.db.conn.commit()
            return {"ok": False, "error": str(exc), "tool": spec.tool["function"]["name"]}
        idem = hashlib.sha256(f"{user_id}|{kind}|{canonical_args(clean)}".encode()).hexdigest()
        now = self._now()
        with self.db.lock:
            self._expire(now)
            done = self.db.conn.execute(
                "SELECT * FROM customer_actions WHERE idem_key=? AND status='executed' AND decided_at>?",
                (idem, (now - timedelta(hours=self.idem_hours)).isoformat(timespec="seconds"))).fetchone()
            if done:
                self._audit(done["action_id"], user_id, session_id, "proposal_already_executed", done["protocol"] or "")
                self.db.conn.commit()
                action = self._row(done)
                return {"ok": True, "tool": spec.tool["function"]["name"], "already_executed": True,
                        "action": self.public(action), "protocol": action["protocol"]}
            # A new proposal in this conversation replaces any other pending one (one decision at a time).
            for old in self.db.conn.execute("SELECT action_id FROM customer_actions WHERE session_id=? AND user_id=? AND status='pending'",
                                            (session_id, user_id)).fetchall():
                self.db.conn.execute("UPDATE customer_actions SET status='superseded', decided_at=? WHERE action_id=?",
                                     (now.isoformat(timespec="seconds"), old["action_id"]))
                self._audit(old["action_id"], user_id, session_id, "superseded")
            token = secrets.token_urlsafe(18)
            action_id = "act_" + secrets.token_hex(8)
            summary = spec.summary(clean, language)
            self.db.conn.execute(
                "INSERT INTO customer_actions(action_id,user_id,session_id,kind,args_json,summary,language,status,token_hash,idem_key,"
                "created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (action_id, user_id, session_id, kind, canonical_args(clean), summary, language, "pending",
                 hashlib.sha256(token.encode()).hexdigest(), idem, now.isoformat(timespec="seconds"),
                 (now + timedelta(seconds=self.ttl)).isoformat(timespec="seconds")))
            self._audit(action_id, user_id, session_id, "proposed", kind)
            self.db.conn.commit()
            row = self.db.conn.execute("SELECT * FROM customer_actions WHERE action_id=?", (action_id,)).fetchone()
        action = self._row(row)
        return {"ok": True, "tool": spec.tool["function"]["name"], "pending_action": self.public(action, token),
                "confirmation_text": self.confirmation_text(action)}

    def confirmation_text(self, action: dict) -> str:
        minutes = max(1, self.ttl // 60)
        if KINDS[action["kind"]].reinforced:
            phrase = reinforced_phrase(action)
            return (f"Preciso da sua confirmação antes de executar: {action['summary']} Para confirmar, digite exatamente "
                    f"\"{phrase}\" (vale por {minutes} min). Para desistir, responda \"cancelar\"."
                    if action["language"] == "pt" else
                    f"I need your confirmation before doing this: {action['summary']} To confirm, type exactly \"{phrase}\" "
                    f"(valid for {minutes} min). To give up, reply \"cancel\".")
        return (f"Posso fazer isto por você: {action['summary']} Confirma? Responda \"sim\" para executar ou \"cancelar\" "
                f"(vale por {minutes} min). Nada é feito sem a sua confirmação."
                if action["language"] == "pt" else
                f"I can do this for you: {action['summary']} Do you confirm? Reply \"yes\" to proceed or \"cancel\" "
                f"(valid for {minutes} min). Nothing is done without your confirmation.")

    # ------------------------------------------------------------------ decide
    def _expire(self, now: datetime) -> None:
        for row in self.db.conn.execute("SELECT action_id,user_id,session_id FROM customer_actions WHERE status='pending' AND expires_at<=?",
                                        (now.isoformat(timespec="seconds"),)).fetchall():
            self.db.conn.execute("UPDATE customer_actions SET status='expired' WHERE action_id=?", (row["action_id"],))
            self._audit(row["action_id"], row["user_id"], row["session_id"], "expired")

    def pending_for_session(self, session_id: str, user_id: str) -> dict | None:
        with self.db.lock:
            self._expire(self._now())
            self.db.conn.commit()
            row = self.db.conn.execute("SELECT * FROM customer_actions WHERE session_id=? AND user_id=? AND status='pending' "
                                       "ORDER BY created_at DESC LIMIT 1", (session_id, user_id)).fetchone()
        return self._row(row) if row else None

    def decide(self, action_id: str, user_id: str, session_id: str, decision: str, *, token: str | None = None,
               typed: str | None = None, channel: str = "chat") -> dict:
        """decision: 'yes' | 'no'. Returns {outcome, action, protocol?, message}."""
        now = self._now()
        with self.db.lock:
            self._expire(now)
            row = self.db.conn.execute("SELECT * FROM customer_actions WHERE action_id=?", (action_id,)).fetchone()
            if row is None or row["user_id"] != user_id:
                self._audit(action_id, user_id, session_id, "decision_rejected", "not_found")
                self.db.conn.commit()
                return {"outcome": "not_found"}
            if row["session_id"] != session_id:
                self._audit(action_id, user_id, session_id, "decision_rejected", "other_session")
                self.db.conn.commit()
                return {"outcome": "not_found"}  # do not reveal actions of other conversations
            if token is not None and not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["token_hash"]):
                self._audit(action_id, user_id, session_id, "decision_rejected", "bad_token")
                self.db.conn.commit()
                return {"outcome": "bad_token"}
            action = self._row(row)
            if row["status"] == "executed":
                self._audit(action_id, user_id, session_id, "repeat_confirmation_ignored", row["protocol"])
                self.db.conn.commit()
                return {"outcome": "already_executed", "action": action, "protocol": row["protocol"]}
            if row["status"] != "pending":
                self.db.conn.commit()
                return {"outcome": row["status"], "action": action}
            if decision == "no":
                self.db.conn.execute("UPDATE customer_actions SET status='cancelled', decided_at=? WHERE action_id=?",
                                     (now.isoformat(timespec="seconds"), action_id))
                self._audit(action_id, user_id, session_id, "cancelled", channel)
                self.db.conn.commit()
                action["status"] = "cancelled"
                return {"outcome": "cancelled", "action": action}
            if KINDS[row["kind"]].reinforced and _fold(typed or "") != _fold(reinforced_phrase(action)):
                self._audit(action_id, user_id, session_id, "decision_rejected", "typed_phrase_missing")
                self.db.conn.commit()
                return {"outcome": "needs_typed_confirmation", "action": action}
            protocol = "ACT-" + now.strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
            self.db.conn.execute("INSERT INTO service_requests(protocol,action_id,user_id,kind,args_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
                                 (protocol, action_id, user_id, row["kind"], row["args_json"], "open", now.isoformat(timespec="seconds")))
            if row["kind"] == "terminal_block":
                self.db.conn.execute("UPDATE terminals SET status='blocked_by_customer' WHERE terminal_id=? AND user_id=?",
                                     (action["args"]["terminal_id"], user_id))
            self.db.conn.execute("UPDATE customer_actions SET status='executed', decided_at=?, protocol=? WHERE action_id=? AND status='pending'",
                                 (now.isoformat(timespec="seconds"), protocol, action_id))
            self._audit(action_id, user_id, session_id, "executed", f"{channel}:{protocol}")
            self.db.conn.commit()
        action.update(status="executed", protocol=protocol)
        return {"outcome": "executed", "action": action, "protocol": protocol}

    def result_text(self, outcome: dict, language: str) -> str:
        """Fixed confirmation-of-protocol text (allowed by the fixed-text policy), built from the record."""
        action, kind = outcome.get("action") or {}, outcome["outcome"]
        pt = language == "pt"
        if kind in ("executed", "already_executed"):
            prefix = ("Feito." if kind == "executed" else "Esta solicitação já tinha sido registrada; nada foi duplicado.") if pt else \
                     ("Done." if kind == "executed" else "This request was already registered; nothing was duplicated.")
            return (f"{prefix} {action['summary']} Protocolo: {outcome['protocol']}. Registro demonstrativo sintético; nenhum sistema real da Getnet foi alterado."
                    if pt else
                    f"{prefix} {action['summary']} Protocol: {outcome['protocol']}. Synthetic demo record; no real Getnet system was changed.")
        if kind == "cancelled":
            return "Cancelado. Nada foi executado." if pt else "Cancelled. Nothing was done."
        if kind == "needs_typed_confirmation":
            phrase = reinforced_phrase(action)
            return (f"Por segurança, este pedido só é executado se você digitar exatamente \"{phrase}\"."
                    if pt else f"For safety, this request only runs if you type exactly \"{phrase}\".")
        if kind == "expired":
            return ("A confirmação expirou e nada foi executado. Se ainda quiser, peça de novo."
                    if pt else "The confirmation expired and nothing was done. Ask again if you still want it.")
        return "Não encontrei uma ação pendente nesta conversa." if pt else "I found no pending action in this conversation."

    def list_for_user(self, user_id: str) -> dict:
        with self.db.lock:
            actions = [self._row(r) for r in self.db.conn.execute(
                "SELECT * FROM customer_actions WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user_id,)).fetchall()]
            audit = [dict(r) for r in self.db.conn.execute(
                "SELECT action_id,event,detail,created_at FROM action_audit WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()]
        return {"actions": [self.public(a) for a in actions], "audit": audit}
