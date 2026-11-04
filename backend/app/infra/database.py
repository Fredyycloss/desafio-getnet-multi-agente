from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..clock import today as clock_today


def add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


class Database:
    """SQLite persistence for demo identity, sales, sessions, handoffs and vectors.

    All merchant/payment records are synthetic fixtures. They are never connected
    to Getnet production systems.
    """

    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("DATABASE_PATH", "/data/getnet_assist.sqlite3")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=20)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self._schema()
            self._seed()

    def _schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
          user_id TEXT PRIMARY KEY, merchant_name TEXT NOT NULL, account_status TEXT NOT NULL,
          segment TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS terminals (
          terminal_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES customers(user_id),
          model TEXT NOT NULL, status TEXT NOT NULL, connection_type TEXT NOT NULL,
          last_seen_at TEXT, error_code TEXT, last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS transactions (
          transaction_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES customers(user_id),
          transaction_date TEXT NOT NULL, amount REAL NOT NULL, net_amount REAL NOT NULL,
          payment_method TEXT NOT NULL, transaction_status TEXT NOT NULL,
          settlement_date TEXT, settlement_status TEXT NOT NULL, error_code TEXT, description TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, transaction_date);
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'pt',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(session_id),
          role TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
        CREATE TABLE IF NOT EXISTS tickets (
          protocol TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT,
          status TEXT NOT NULL, queue TEXT NOT NULL, real_agent_connected INTEGER NOT NULL DEFAULT 0,
          reason TEXT NOT NULL, severity TEXT NOT NULL, language TEXT NOT NULL,
          summary TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          assigned_operator TEXT, resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_user_status ON tickets(user_id, status);
        CREATE TABLE IF NOT EXISTS ticket_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT NOT NULL REFERENCES tickets(protocol),
          role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_embeddings (
          doc_key TEXT NOT NULL, model TEXT NOT NULL, vector_json TEXT NOT NULL,
          PRIMARY KEY(doc_key, model)
        );
        CREATE TABLE IF NOT EXISTS tool_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL, tool_name TEXT NOT NULL,
          user_id TEXT NOT NULL, status TEXT NOT NULL, duration_ms INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stage_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
          stage_name TEXT NOT NULL, component TEXT NOT NULL, status TEXT NOT NULL,
          duration_ms REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_stage_audit_trace ON stage_audit(trace_id, id);
        CREATE TABLE IF NOT EXISTS model_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL, purpose TEXT NOT NULL,
          model TEXT, prompt_tokens INTEGER, output_tokens INTEGER, load_ms REAL,
          prompt_ms REAL, generation_ms REAL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_model_audit_trace ON model_audit(trace_id, id);
        """)
        # Lightweight forward-only migration for databases created by earlier demos.
        model_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(model_audit)").fetchall()}
        for column, kind in (("provider", "TEXT"), ("latency_ms", "REAL"), ("cost_usd", "REAL")):
            if column not in model_columns:
                self.conn.execute(f"ALTER TABLE model_audit ADD COLUMN {column} {kind}")
        ticket_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(tickets)").fetchall()}
        if "assigned_operator" not in ticket_columns:
            self.conn.execute("ALTER TABLE tickets ADD COLUMN assigned_operator TEXT")
        if "resolved_at" not in ticket_columns:
            self.conn.execute("ALTER TABLE tickets ADD COLUMN resolved_at TEXT")
        for column, kind in (("operator_summary", "TEXT"), ("telegram_message_id", "INTEGER"), ("ai_instruction", "TEXT"),
                             ("resume_pending", "INTEGER NOT NULL DEFAULT 0"), ("resolution", "TEXT")):
            if column not in ticket_columns:
                self.conn.execute(f"ALTER TABLE tickets ADD COLUMN {column} {kind}")
        self.conn.execute("CREATE TABLE IF NOT EXISTS telegram_messages (message_id INTEGER PRIMARY KEY, protocol TEXT NOT NULL)")
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _seed(self) -> None:
        now = self._now()
        yesterday = clock_today() - timedelta(days=1)
        three_days_ago = clock_today() - timedelta(days=3)
        due = add_business_days(yesterday, 2).isoformat()
        customers = [
            ("cliente1988", "Comércio Demo 1988", "active", "small_business", now),
            ("demo-user-001", "Loja Exemplo Centro", "active", "micro_business", now),
            ("demo-merchant-001", "Mercado Demonstração", "active", "medium_business", now),
        ]
        self.conn.executemany("INSERT OR IGNORE INTO customers VALUES(?,?,?,?,?)", customers)
        terminals = [
            ("TERM-1988", "cliente1988", "Get Smart", "offline", "Wi-Fi", now, "NET-001", "Perda de conectividade (fixture demonstrativa)"),
            ("TERM-001", "demo-user-001", "Get Clássica", "online", "4G", now, None, None),
            ("TERM-002", "demo-merchant-001", "Get Lite", "online", "Wi-Fi", now, None, None),
        ]
        self.conn.executemany("INSERT OR IGNORE INTO terminals VALUES(?,?,?,?,?,?,?,?)", terminals)
        transactions = [
            ("TX-DEMO-1001", "cliente1988", yesterday.isoformat(), 250.00, 242.75, "credit", "approved", due, "scheduled", None, "Venda demonstrativa de crédito"),
            ("TX-DEMO-1002", "cliente1988", yesterday.isoformat(), 120.00, 118.80, "debit", "approved", add_business_days(yesterday, 1).isoformat(), "scheduled", None, "Venda demonstrativa de débito"),
            ("TX-DEMO-1003", "cliente1988", yesterday.isoformat(), 89.90, 0.00, "credit", "declined", None, "not_applicable", "05", "Transação demonstrativa recusada pelo emissor"),
            ("TX-DEMO-2001", "demo-user-001", yesterday.isoformat(), 420.00, 407.40, "credit", "approved", add_business_days(yesterday, 2).isoformat(), "scheduled", None, "Venda demonstrativa de crédito"),
            # V7-F fixtures for disputes: an older sale of 1988 (outside "yesterday", so its daily totals are unchanged),
            # a declined sale for demo-user-001 and a sale for demo-merchant-001.
            ("TX-DEMO-1005", "cliente1988", three_days_ago.isoformat(), 59.90, 58.15, "credit", "approved", add_business_days(three_days_ago, 2).isoformat(), "scheduled", None, "Venda demonstrativa de crédito (candidata a contestação)"),
            ("TX-DEMO-2002", "demo-user-001", yesterday.isoformat(), 35.00, 0.00, "debit", "declined", None, "not_applicable", "51", "Transação demonstrativa recusada: saldo insuficiente"),
            ("TX-DEMO-3001", "demo-merchant-001", yesterday.isoformat(), 75.00, 74.25, "debit", "approved", add_business_days(yesterday, 1).isoformat(), "scheduled", None, "Venda demonstrativa de débito"),
        ]
        self.conn.executemany("INSERT OR IGNORE INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)", transactions)
        # Keep the seeded demo scenario relative to the actual runtime date.
        self.conn.execute("UPDATE transactions SET transaction_date=?, settlement_date=? WHERE transaction_id='TX-DEMO-1001'", (yesterday.isoformat(), due))
        self.conn.execute("UPDATE transactions SET transaction_date=?, settlement_date=? WHERE transaction_id='TX-DEMO-1002'", (yesterday.isoformat(), add_business_days(yesterday, 1).isoformat()))
        self.conn.execute("UPDATE transactions SET transaction_date=? WHERE transaction_id='TX-DEMO-1003'", (yesterday.isoformat(),))
        self.conn.execute("UPDATE transactions SET transaction_date=?, settlement_date=? WHERE transaction_id='TX-DEMO-2001'", (yesterday.isoformat(), add_business_days(yesterday, 2).isoformat()))
        self.conn.execute("UPDATE transactions SET transaction_date=?, settlement_date=? WHERE transaction_id='TX-DEMO-1005'", (three_days_ago.isoformat(), add_business_days(three_days_ago, 2).isoformat()))
        self.conn.execute("UPDATE transactions SET transaction_date=? WHERE transaction_id='TX-DEMO-2002'", (yesterday.isoformat(),))
        self.conn.execute("UPDATE transactions SET transaction_date=?, settlement_date=? WHERE transaction_id='TX-DEMO-3001'", (yesterday.isoformat(), add_business_days(yesterday, 1).isoformat()))
        self.conn.commit()

    def ensure_session(self, session_id: str, user_id: str) -> None:
        now = self._now()
        with self.lock:
            existing = self.conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if existing and existing["user_id"] != user_id:
                raise PermissionError("session_owner_mismatch")
            self.conn.execute("INSERT OR IGNORE INTO sessions(session_id,user_id,created_at,updated_at) VALUES(?,?,?,?)", (session_id, user_id, now, now))
            self.conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=? AND user_id=?", (now, session_id, user_id))
            self.conn.commit()

    def save_message(self, session_id: str, user_id: str, role: str, content: str, metadata: dict | None = None) -> None:
        self.ensure_session(session_id, user_id)
        with self.lock:
            self.conn.execute("INSERT INTO messages(session_id,role,content,metadata_json,created_at) VALUES(?,?,?,?,?)", (session_id, role, content[:4000], json.dumps(metadata or {}, ensure_ascii=False), self._now()))
            self.conn.commit()

    def get_session_owner(self, session_id: str) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return row["user_id"] if row else None

    def get_history(self, session_id: str, limit: int = 12) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT id,role,content,metadata_json FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
        history = []
        for row in reversed(rows):
            item = {"role": row["role"], "content": row["content"], "id": row["id"]}
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if isinstance(metadata, dict) and isinstance(metadata.get("clarification_options"), list):
                item["clarification_options"] = metadata["clarification_options"]
            if isinstance(metadata, dict):
                for key in ("author", "hidden", "handoff_protocol", "handoff_status", "operator"):
                    if key in metadata:
                        item[key] = metadata[key]
            history.append(item)
        return history

    def last_message_id(self, session_id: str) -> int:
        with self.lock:
            row = self.conn.execute("SELECT MAX(id) AS m FROM messages WHERE session_id=?", (session_id,)).fetchone()
        return int(row["m"] or 0)

    def messages_after(self, session_id: str, after_id: int = 0, limit: int = 50) -> list[dict]:
        """Messages newer than ``after_id`` (live updates for the customer UI); hidden notes excluded."""
        with self.lock:
            rows = self.conn.execute("SELECT id,role,content,metadata_json,created_at FROM messages WHERE session_id=? AND id>? ORDER BY id LIMIT ?",
                                     (session_id, after_id, limit)).fetchall()
        out = []
        for row in rows:
            meta = json.loads(row["metadata_json"] or "{}")
            if meta.get("hidden"):
                continue
            out.append({"id": row["id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"],
                        **{k: meta[k] for k in ("author", "operator", "handoff_protocol", "handoff_status") if k in meta}})
        return out

    def get_customer(self, user_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT user_id,merchant_name,account_status,segment FROM customers WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_terminal(self, user_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT terminal_id,model,status,connection_type,last_seen_at,error_code,last_error FROM terminals WHERE user_id=? ORDER BY terminal_id LIMIT 1", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_transactions(self, user_id: str, *, day: str | None = None, status: str | None = None, limit: int = 20) -> list[dict]:
        query = "SELECT transaction_id,transaction_date,amount,net_amount,payment_method,transaction_status,settlement_date,settlement_status,error_code,description FROM transactions WHERE user_id=?"
        params: list[Any] = [user_id]
        if day:
            query += " AND transaction_date=?"
            params.append(day)
        if status:
            query += " AND transaction_status=?"
            params.append(status)
        query += " ORDER BY transaction_date DESC, transaction_id LIMIT ?"
        params.append(max(1, min(limit, 50)))
        with self.lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def create_ticket(
        self,
        user_id: str,
        session_id: str | None,
        reason: str,
        severity: str,
        language: str,
        summary: str,
        history: list[dict] | None = None,
    ) -> dict:
        summary = self._redact(summary)
        with self.lock:
            existing = self.conn.execute(
                "SELECT protocol FROM tickets WHERE user_id=? AND reason=? AND status='queued' "
                "AND ((session_id IS NULL AND ? IS NULL) OR session_id=?) ORDER BY created_at DESC LIMIT 1",
                (user_id, reason, session_id, session_id),
            ).fetchone()
            if existing:
                protocol = existing["protocol"]
                self.conn.execute("UPDATE tickets SET summary=?,updated_at=? WHERE protocol=?", (summary, self._now(), protocol))
                self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, "user", summary, self._now()))
            else:
                protocol = f"GET-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"
                now = self._now()
                self.conn.execute("INSERT INTO tickets(protocol,user_id,session_id,status,queue,real_agent_connected,reason,severity,language,summary,created_at,updated_at) VALUES(?,?,?,'queued','simulated_human_support',0,?,?,?,?,?,?)", (protocol, user_id, session_id, reason, severity, language, summary, now, now))
                safe_history = [
                    (item.get("role"), self._redact(str(item.get("content", ""))))
                    for item in (history or [])[-10:]
                    if item.get("role") in {"user", "assistant"} and str(item.get("content", "")).strip()
                ]
                for role, content in safe_history:
                    if role == "user" and content == summary:
                        continue
                    self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, role, content[:4000], self._now()))
                if not safe_history or safe_history[-1] != ("user", summary):
                    self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, "user", summary, self._now()))
            self.conn.commit()
        return self.get_ticket(protocol) or {}

    @staticmethod
    def _redact(text: str) -> str:
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email redacted]", (text or "")[:1000])
        value = re.sub(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", "[card number redacted]", value)
        return re.sub(r"(?i)\b(password|senha|token|otp|cvv|cvc)\s*[:=]?\s*\S+", r"\1 [redacted]", value)

    def get_ticket(self, protocol: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM tickets WHERE protocol=?", (protocol.upper(),)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["real_agent_connected"] = bool(data["real_agent_connected"])
            data["messages"] = [dict(item) for item in self.conn.execute("SELECT role,content,created_at FROM ticket_messages WHERE protocol=? ORDER BY id", (protocol.upper(),)).fetchall()]
        return data

    def list_tickets(self, status: str | None = None) -> list[dict]:
        with self.lock:
            if status:
                rows = self.conn.execute("SELECT protocol FROM tickets WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = self.conn.execute("SELECT protocol FROM tickets ORDER BY created_at DESC").fetchall()
        return [ticket for row in rows if (ticket := self.get_ticket(row["protocol"])) is not None]

    def append_ticket_message(self, protocol: str, message: str) -> dict | None:
        safe = self._redact(message)
        with self.lock:
            exists = self.conn.execute("SELECT 1 FROM tickets WHERE protocol=?", (protocol.upper(),)).fetchone()
            if not exists:
                return None
            self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol.upper(), "user", safe, self._now()))
            self.conn.execute("UPDATE tickets SET updated_at=? WHERE protocol=?", (self._now(), protocol.upper()))
            self.conn.commit()
        return self.get_ticket(protocol)


    def set_ticket_fields(self, protocol: str, **fields) -> None:
        allowed = {"operator_summary", "telegram_message_id", "ai_instruction", "resume_pending", "resolution"}
        items = {k: v for k, v in fields.items() if k in allowed}
        if not items:
            return
        with self.lock:
            self.conn.execute(f"UPDATE tickets SET {', '.join(f'{k}=?' for k in items)}, updated_at=? WHERE protocol=?",
                              (*items.values(), self._now(), protocol.upper()))
            if items.get("telegram_message_id"):
                self.conn.execute("INSERT OR REPLACE INTO telegram_messages(message_id,protocol) VALUES(?,?)",
                                  (items["telegram_message_id"], protocol.upper()))
            self.conn.commit()

    def map_telegram_message(self, message_id: int | None, protocol: str) -> None:
        if message_id:
            with self.lock:
                self.conn.execute("INSERT OR REPLACE INTO telegram_messages(message_id,protocol) VALUES(?,?)", (message_id, protocol.upper()))
                self.conn.commit()

    def protocol_for_telegram_message(self, message_id: int) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT protocol FROM telegram_messages WHERE message_id=?", (message_id,)).fetchone()
        return row["protocol"] if row else None

    def active_ticket_for_session(self, session_id: str) -> dict | None:
        """The ticket of this session currently handled by a human (status assigned)."""
        with self.lock:
            row = self.conn.execute("SELECT protocol FROM tickets WHERE session_id=? AND status='assigned' ORDER BY updated_at DESC LIMIT 1",
                                    (session_id,)).fetchone()
        return self.get_ticket(row["protocol"]) if row else None

    def latest_ticket_for_session(self, session_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT protocol FROM tickets WHERE session_id=? ORDER BY created_at DESC, updated_at DESC LIMIT 1",
                                    (session_id,)).fetchone()
        return self.get_ticket(row["protocol"]) if row else None

    def return_ticket_to_ai(self, protocol: str, operator_id: str, instruction: str) -> dict | None:
        protocol = protocol.upper()
        safe = self._redact(instruction)
        with self.lock:
            row = self.conn.execute("SELECT status,assigned_operator FROM tickets WHERE protocol=?", (protocol,)).fetchone()
            if not row:
                return None
            if row["status"] != "assigned" or row["assigned_operator"] != operator_id:
                raise ValueError("ticket_not_assigned_to_operator")
            now = self._now()
            self.conn.execute("UPDATE tickets SET status='returned_to_ai',ai_instruction=?,resume_pending=1,resolved_at=?,updated_at=? WHERE protocol=?",
                              (safe, now, now, protocol))
            self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, "operator", f"Returned to AI: {safe}", now))
            self.conn.commit()
        return self.get_ticket(protocol)

    def claim_ticket(self, protocol: str, operator_id: str) -> dict | None:
        protocol = protocol.upper()
        with self.lock:
            row = self.conn.execute("SELECT status,assigned_operator FROM tickets WHERE protocol=?", (protocol,)).fetchone()
            if not row:
                return None
            if row["status"] in {"resolved", "returned_to_ai"}:
                raise ValueError("ticket_already_resolved")
            if row["assigned_operator"] and row["assigned_operator"] != operator_id:
                raise ValueError("ticket_already_assigned")
            now = self._now()
            self.conn.execute("UPDATE tickets SET status='assigned',assigned_operator=?,updated_at=? WHERE protocol=?", (operator_id, now, protocol))
            self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, "operator", f"Ticket claimed by operator {operator_id}.", now))
            self.conn.commit()
        return self.get_ticket(protocol)

    def append_operator_message(self, protocol: str, operator_id: str, message: str) -> dict | None:
        protocol = protocol.upper()
        safe = self._redact(message)
        with self.lock:
            row = self.conn.execute("SELECT status,assigned_operator FROM tickets WHERE protocol=?", (protocol,)).fetchone()
            if not row:
                return None
            if row["status"] != "assigned" or row["assigned_operator"] != operator_id:
                raise ValueError("ticket_not_assigned_to_operator")
            now = self._now()
            self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, "operator", safe, now))
            self.conn.execute("UPDATE tickets SET updated_at=? WHERE protocol=?", (now, protocol))
            self.conn.commit()
        return self.get_ticket(protocol)

    def resolve_ticket(self, protocol: str, operator_id: str, resolution: str) -> dict | None:
        protocol = protocol.upper()
        safe = self._redact(resolution)
        with self.lock:
            row = self.conn.execute("SELECT status,assigned_operator FROM tickets WHERE protocol=?", (protocol,)).fetchone()
            if not row:
                return None
            if row["status"] != "assigned" or row["assigned_operator"] != operator_id:
                raise ValueError("ticket_not_assigned_to_operator")
            now = self._now()
            self.conn.execute("UPDATE tickets SET status='resolved',resolution=?,resolved_at=?,updated_at=? WHERE protocol=?", (safe, now, now, protocol))
            self.conn.execute("INSERT INTO ticket_messages(protocol,role,content,created_at) VALUES(?,?,?,?)", (protocol, "operator", f"Resolution: {safe}", now))
            self.conn.commit()
        return self.get_ticket(protocol)

    def save_embedding(self, doc_key: str, model: str, vector: list[float]) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO document_embeddings(doc_key,model,vector_json) VALUES(?,?,?)", (doc_key, model, json.dumps(vector)))
            self.conn.commit()

    def get_embedding(self, doc_key: str, model: str) -> list[float] | None:
        with self.lock:
            row = self.conn.execute("SELECT vector_json FROM document_embeddings WHERE doc_key=? AND model=?", (doc_key, model)).fetchone()
        return json.loads(row["vector_json"]) if row else None

    def record_tool(self, trace_id: str, tool_name: str, user_id: str, status: str, duration_ms: int) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO tool_audit(trace_id,tool_name,user_id,status,duration_ms,created_at) VALUES(?,?,?,?,?,?)", (trace_id, tool_name, user_id[:128], status, duration_ms, self._now()))
            self.conn.commit()

    def get_tool_metrics(self) -> dict:
        with self.lock:
            rows = self.conn.execute(
                "SELECT tool_name,COUNT(*) AS calls,SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) AS failures,"
                "ROUND(AVG(duration_ms),2) AS average_duration_ms FROM tool_audit GROUP BY tool_name ORDER BY tool_name"
            ).fetchall()
        items = [dict(row) for row in rows]
        return {"calls": sum(item["calls"] for item in items),
                "failures": sum(item["failures"] or 0 for item in items),
                "by_tool": items}

    def record_stages(self, trace_id: str, events: list[dict]) -> None:
        """Persist PII-free stage telemetry after a request completes."""
        rows = [
            (
                trace_id,
                str(item.get("stage", "unknown"))[:120],
                str(item.get("component", "unknown"))[:80],
                str(item.get("status", "error"))[:24],
                max(0.0, float(item.get("duration_ms", 0))),
                self._now(),
            )
            for item in events
        ]
        if not rows:
            return
        with self.lock:
            self.conn.executemany(
                "INSERT INTO stage_audit(trace_id,stage_name,component,status,duration_ms,created_at) VALUES(?,?,?,?,?,?)",
                rows,
            )
            self.conn.commit()

    def get_stage_metrics(self) -> dict:
        with self.lock:
            rows = self.conn.execute(
                "SELECT stage_name AS stage,component,COUNT(*) AS calls,"
                "SUM(CASE WHEN status='ok' THEN 0 ELSE 1 END) AS failures,"
                "SUM(CASE WHEN status='timeout' THEN 1 ELSE 0 END) AS timeouts,"
                "ROUND(AVG(duration_ms),2) AS average_duration_ms,"
                "ROUND(MAX(duration_ms),2) AS max_duration_ms "
                "FROM stage_audit GROUP BY stage_name,component ORDER BY component,stage_name"
            ).fetchall()
        items = [dict(row) for row in rows]
        return {
            "calls": sum(item["calls"] for item in items),
            "failures": sum(item["failures"] or 0 for item in items),
            "timeouts": sum(item["timeouts"] or 0 for item in items),
            "by_stage": items,
        }

    def record_model_calls(self, trace_id: str, calls: list[dict]) -> None:
        """Persist per-call LLM counters (token counts and durations only, no content)."""
        def num(value, cast):
            return cast(value) if isinstance(value, (int, float)) else None

        rows = [
            (
                trace_id, str(call.get("purpose", "chat"))[:80], str(call.get("model") or "")[:80] or None,
                num(call.get("prompt_tokens"), int), num(call.get("output_tokens"), int),
                num(call.get("load_ms"), float), num(call.get("prompt_ms"), float),
                num(call.get("generation_ms"), float), self._now(),
                str(call.get("provider") or "")[:40] or None, num(call.get("latency_ms"), float),
                num(call.get("cost_usd"), float),
            )
            for call in calls
        ]
        if not rows:
            return
        with self.lock:
            self.conn.executemany(
                "INSERT INTO model_audit(trace_id,purpose,model,prompt_tokens,output_tokens,load_ms,prompt_ms,generation_ms,created_at,"
                "provider,latency_ms,cost_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self.conn.commit()

    def get_model_metrics(self) -> dict:
        with self.lock:
            rows = self.conn.execute(
                "SELECT purpose,COUNT(*) AS calls,SUM(prompt_tokens) AS prompt_tokens,SUM(output_tokens) AS output_tokens,"
                "ROUND(AVG(prompt_tokens),1) AS average_prompt_tokens,ROUND(AVG(output_tokens),1) AS average_output_tokens,"
                "ROUND(AVG(load_ms),2) AS average_load_ms,ROUND(AVG(prompt_ms),2) AS average_prompt_ms,"
                "ROUND(AVG(generation_ms),2) AS average_generation_ms,ROUND(AVG(latency_ms),2) AS average_latency_ms,"
                "ROUND(SUM(COALESCE(cost_usd,0)),6) AS cost_usd "
                "FROM model_audit GROUP BY purpose ORDER BY purpose"
            ).fetchall()
            requests = self.conn.execute("SELECT COUNT(DISTINCT trace_id) FROM model_audit").fetchone()[0]
            providers = [dict(row) for row in self.conn.execute(
                "SELECT COALESCE(provider,'ollama') AS provider,model,COUNT(*) AS calls,"
                "ROUND(SUM(COALESCE(cost_usd,0)),6) AS cost_usd FROM model_audit GROUP BY 1,2 ORDER BY 1,2").fetchall()]
        items = [dict(row) for row in rows]
        calls = sum(item["calls"] for item in items)
        return {
            "calls": calls,
            "requests_with_llm": requests,
            "average_calls_per_request": round(calls / requests, 2) if requests else 0,
            "prompt_tokens": sum(item["prompt_tokens"] or 0 for item in items),
            "output_tokens": sum(item["output_tokens"] or 0 for item in items),
            "cost_usd": round(sum(item["cost_usd"] or 0 for item in items), 6),
            "average_cost_per_request_usd": round(sum(item["cost_usd"] or 0 for item in items) / requests, 6) if requests else 0,
            "by_provider": providers,
            "by_purpose": items,
        }

    def close(self) -> None:
        with self.lock:
            self.conn.close()
