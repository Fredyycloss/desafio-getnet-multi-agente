"""Individual operator accounts: hashed passwords (scrypt), roles, expiring tokens, audit.

Roles: ``operator`` (claim, reply, resolve, return to AI) and ``supervisor`` (also sees the
whole queue and the knowledge-gap queue). Demo operators exist only with DEMO_MODE=true;
otherwise accounts are created with ``python -m app.hitl.operators add <user> --role ...``.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sys
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS operators (
  username TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL,
  password_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operator_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, operator TEXT NOT NULL, channel TEXT NOT NULL, action TEXT NOT NULL,
  protocol TEXT, outcome TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_heartbeat (name TEXT PRIMARY KEY, last_seen REAL NOT NULL);
"""
ROLES = {"operator", "supervisor"}
# Public demo accounts (synthetic environment only, DEMO_MODE=true).
DEMO_OPERATORS = {"ana.operadora": ("Ana (operadora)", "operator", "demo-ana-2026"),
                  "bruno.supervisor": ("Bruno (supervisor)", "supervisor", "demo-bruno-2026")}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
    return digest.hex(), salt


def demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").strip().lower() == "true"


def ensure_schema(db) -> None:
    with db.lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()
    if demo_mode():
        for username, (display, role, password) in DEMO_OPERATORS.items():
            if get_operator(db, username) is None:
                add_operator(db, username, password, role=role, display_name=display)


def add_operator(db, username: str, password: str, *, role: str = "operator", display_name: str | None = None) -> None:
    if role not in ROLES:
        raise ValueError("invalid_role")
    if len(password) < 10:
        raise ValueError("password_too_short")
    digest, salt = hash_password(password)
    with db.lock:
        db.conn.execute("INSERT OR REPLACE INTO operators(username,display_name,role,password_hash,salt,active,created_at) "
                        "VALUES(?,?,?,?,?,1,?)", (username, display_name or username, role, digest, salt, _now()))
        db.conn.commit()


def get_operator(db, username: str) -> dict | None:
    with db.lock:
        row = db.conn.execute("SELECT username,display_name,role,active,password_hash,salt FROM operators WHERE username=?",
                              (username,)).fetchone()
    return dict(row) if row else None


def verify_operator(db, username: str, password: str) -> dict | None:
    """Constant-time check; a dummy hash is computed for unknown users."""
    op = get_operator(db, username)
    salt = op["salt"] if op else "00" * 16
    digest, _ = hash_password(password, salt)
    ok = bool(op) and op["active"] and hmac.compare_digest(digest, op["password_hash"])
    return {"username": op["username"], "display_name": op["display_name"], "role": op["role"]} if ok else None


def audit(db, operator: str, channel: str, action: str, protocol: str | None, outcome: str) -> None:
    with db.lock:
        db.conn.execute("INSERT INTO operator_audit(operator,channel,action,protocol,outcome,created_at) VALUES(?,?,?,?,?,?)",
                        (operator[:80], channel, action, protocol, outcome[:120], _now()))
        db.conn.commit()


def list_audit(db, limit: int = 100) -> list[dict]:
    with db.lock:
        rows = db.conn.execute("SELECT operator,channel,action,protocol,outcome,created_at FROM operator_audit ORDER BY id DESC LIMIT ?",
                               (limit,)).fetchall()
    return [dict(r) for r in rows]


def heartbeat(db, name: str) -> None:
    import time
    with db.lock:
        db.conn.execute("INSERT OR REPLACE INTO channel_heartbeat(name,last_seen) VALUES(?,?)", (name, time.time()))
        db.conn.commit()


def active_channels(db, within_seconds: float = 90.0) -> list[str]:
    import time
    with db.lock:
        rows = db.conn.execute("SELECT name FROM channel_heartbeat WHERE last_seen>=?", (time.time() - within_seconds,)).fetchall()
    return [r["name"] for r in rows]


def main() -> int:
    from ..infra.database import Database
    parser = argparse.ArgumentParser(description="Manage operator accounts")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("username")
    add.add_argument("--role", default="operator", choices=sorted(ROLES))
    add.add_argument("--display-name")
    args = parser.parse_args()
    db = Database()
    ensure_schema(db)
    password = getpass.getpass("Password (min 10 chars, hidden): ")
    try:
        add_operator(db, args.username, password, role=args.role, display_name=args.display_name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"operator {args.username} saved ({args.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
