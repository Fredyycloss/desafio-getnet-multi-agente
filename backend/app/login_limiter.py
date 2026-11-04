"""Login rate limiting and lockout, shared by every API replica through the database.

Two keys are counted per attempt: the account (``cust:<user_id>`` / ``op:<username>``) and the
client address (``ip:<addr>``). After LOGIN_MAX_FAILURES failures inside LOGIN_WINDOW_SECONDS
the key is locked for LOGIN_LOCKOUT_SECONDS; the address key also has a hard request ceiling
(LOGIN_MAX_REQUESTS_PER_MINUTE) so one client cannot spray many accounts. A success clears the
account's failures. Answers never reveal whether an account exists.
"""
from __future__ import annotations

import os
import time


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class LoginLimiter:
    def __init__(self, db):
        self.db = db
        self.max_failures = _int("LOGIN_MAX_FAILURES", 5)
        self.window = _int("LOGIN_WINDOW_SECONDS", 300)
        self.lockout = _int("LOGIN_LOCKOUT_SECONDS", 300)
        self.per_minute = _int("LOGIN_MAX_REQUESTS_PER_MINUTE", 30)
        with db.lock:
            db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS login_attempts (key TEXT NOT NULL, at REAL NOT NULL, ok INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_login_attempts_key ON login_attempts(key, at);
            CREATE TABLE IF NOT EXISTS login_lockouts (key TEXT PRIMARY KEY, until REAL NOT NULL);
            """)
            db.conn.commit()

    def _locked_until(self, key: str) -> float:
        row = self.db.conn.execute("SELECT until FROM login_lockouts WHERE key=?", (key,)).fetchone()
        return float(row[0]) if row else 0.0

    def check(self, *keys: str) -> int:
        """0 if every key may try now, else seconds until the longest lock or rate window ends."""
        now = time.time()
        wait = 0.0
        with self.db.lock:
            for key in keys:
                wait = max(wait, self._locked_until(key) - now)
                if key.startswith("ip:"):
                    recent = self.db.conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key=? AND at>?", (key, now - 60)).fetchone()[0]
                    if recent >= self.per_minute:
                        wait = max(wait, 60.0)
        return max(0, int(wait + 0.999))

    def record(self, ok: bool, *keys: str) -> None:
        now = time.time()
        with self.db.lock:
            for key in keys:
                self.db.conn.execute("INSERT INTO login_attempts(key,at,ok) VALUES(?,?,?)", (key, now, int(ok)))
                if ok and not key.startswith("ip:"):
                    self.db.conn.execute("DELETE FROM login_attempts WHERE key=? AND ok=0", (key,))
                    self.db.conn.execute("DELETE FROM login_lockouts WHERE key=?", (key,))
                    continue
                if not ok and not key.startswith("ip:"):  # addresses: per-minute ceiling only
                    failures = self.db.conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key=? AND ok=0 AND at>?",
                                                    (key, now - self.window)).fetchone()[0]
                    if failures >= self.max_failures:
                        self.db.conn.execute("INSERT OR REPLACE INTO login_lockouts(key,until) VALUES(?,?)", (key, now + self.lockout))
            self.db.conn.execute("DELETE FROM login_attempts WHERE at<?", (now - max(self.window, 3600),))
            self.db.conn.commit()

    def hit(self, key: str, per_minute: int) -> int:
        """Count one request for ``key`` (e.g. ``chat:<user>``); seconds to wait if over the limit."""
        now = time.time()
        with self.db.lock:
            recent = self.db.conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key=? AND at>?", (key, now - 60)).fetchone()[0]
            if recent >= per_minute:
                oldest = self.db.conn.execute("SELECT MIN(at) FROM login_attempts WHERE key=? AND at>?", (key, now - 60)).fetchone()[0]
                return max(1, int(oldest + 60 - now + 0.999))
            self.db.conn.execute("INSERT INTO login_attempts(key,at,ok) VALUES(?,?,1)", (key, now))
            self.db.conn.commit()
        return 0

    # Compatibility with the operator router (single-key calls).
    def allow(self, key: str) -> bool:
        return self.check(key) == 0

    def retry_after(self, key: str) -> int:
        return self.check(key)

    def fail(self, key: str) -> None:
        self.record(False, key)

    def success(self, key: str) -> None:
        self.record(True, key)
