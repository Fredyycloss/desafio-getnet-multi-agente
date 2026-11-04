from __future__ import annotations

import pytest

from app.infra.database import Database
from app.knowledge.ingest import load_documents


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.sqlite3"))
    yield database
    database.close()


@pytest.fixture(autouse=True)
def _no_live_site_reads(monkeypatch):
    """Unit tests never reach the official websites (the live-read tool is tested with a stub)."""
    monkeypatch.setenv("KNOWLEDGE_LIVE_READ", "false")


@pytest.fixture(scope="session")
def _snapshot_documents():
    return load_documents()


@pytest.fixture
def documents(_snapshot_documents):
    """The runtime knowledge base (latest official-site snapshot)."""
    return _snapshot_documents


@pytest.fixture
def legacy_documents():
    """The 26 hand-written summaries of the previous version (BM25 mechanics regression only)."""
    from app.knowledge.ingest import load_legacy_curated
    return load_legacy_curated()


def _claimed_user(url: str, kwargs: dict) -> str | None:
    from urllib.parse import parse_qs, urlparse
    body = kwargs.get("json")
    if isinstance(body, dict) and body.get("user_id"):
        return str(body["user_id"])
    params = kwargs.get("params") or {}
    if isinstance(params, dict) and params.get("user_id"):
        return str(params["user_id"])
    query = parse_qs(urlparse(str(url)).query)
    return query.get("user_id", [None])[0]


try:
    from fastapi.testclient import TestClient as _TestClient

    class AutoAuthClient(_TestClient):
        """Logs in (demo PIN) as the user_id a request claims, so pre-auth API tests keep
        asserting the same behaviour. Tests of the auth boundary use plain TestClient."""

        def request(self, method, url, **kwargs):
            from app.auth import DEMO_USERS
            headers = dict(kwargs.pop("headers", None) or {})
            user = _claimed_user(url, kwargs)
            if "Authorization" not in headers and user in DEMO_USERS:
                token = super().request("POST", "/api/auth/demo-login",
                                        json={"user_id": user, "pin": DEMO_USERS[user]["pin"]}).json()["access_token"]
                headers["Authorization"] = f"Bearer {token}"
            return super().request(method, url, headers=headers, **kwargs)
except ImportError:  # pragma: no cover
    pass
