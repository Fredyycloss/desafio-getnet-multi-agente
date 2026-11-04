"""Demo authentication: synthetic users, PIN login and HMAC-signed bearer tokens.

The identity used by /api/chat, sessions and protocols comes from the token, never
from the request body. A body user_id that differs from the token is rejected (403).
This is a demonstration scheme for synthetic fixtures, not production identity.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

# Synthetic demo merchants (same ids as the fixtures in infra/database.py).
DEMO_USERS = {
    "cliente1988": {"pin": "1988", "merchant_name": "Comércio Demo 1988"},
    "demo-user-001": {"pin": "0001", "merchant_name": "Loja Exemplo Centro"},
    "demo-merchant-001": {"pin": "0002", "merchant_name": "Mercado Demonstração"},
}

_process_secret = secrets.token_bytes(32)


def _secret() -> bytes:
    configured = os.getenv("AUTH_SECRET", "").strip()
    return configured.encode() if configured else _process_secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_pin(user_id: str, pin: str) -> bool:
    user = DEMO_USERS.get(user_id)
    # compare_digest on both branches keeps timing independent of user existence.
    expected = user["pin"] if user else "\0" * 8
    return hmac.compare_digest(expected.encode(), str(pin).encode()) and user is not None


def issue_token(user_id: str, ttl_seconds: int | None = None) -> dict:
    ttl = int(ttl_seconds or os.getenv("AUTH_TOKEN_TTL_SECONDS", "3600"))
    now = int(time.time())
    claims = {"sub": user_id, "iat": now, "exp": now + ttl}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return {"access_token": f"{body}.{signature}", "token_type": "bearer", "expires_in": ttl, "user_id": user_id}


def verify_token(token: str) -> str | None:
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        claims = json.loads(_unb64(body))
        if int(claims.get("exp", 0)) < int(time.time()):
            return None
        subject = str(claims.get("sub") or "")
        return subject if subject in DEMO_USERS else None
    except (ValueError, json.JSONDecodeError, TypeError):
        return None


def sign_claims(claims: dict, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())}"


def verify_claims(token: str) -> dict | None:
    """Signature + expiry check; returns the claims (any token kind) or None."""
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        claims = json.loads(_unb64(body))
        return claims if int(claims.get("exp", 0)) >= int(time.time()) else None
    except (ValueError, json.JSONDecodeError, TypeError):
        return None


def issue_operator_token(operator: dict) -> dict:
    """Operator session token (kind=operator); never accepted on customer endpoints."""
    ttl = int(os.getenv("OPERATOR_TOKEN_TTL_SECONDS", "28800"))
    token = sign_claims({"sub": f"op:{operator['username']}", "kind": "operator", "role": operator["role"],
                         "name": operator["display_name"]}, ttl)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl, **operator}


def require_user(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: the authenticated user_id or 401."""
    scheme, _, token = (authorization or "").partition(" ")
    user_id = verify_token(token.strip()) if scheme.lower() == "bearer" and token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required: POST /api/auth/demo-login",
                            headers={"WWW-Authenticate": "Bearer"})
    return user_id


def ensure_same_user(token_user: str, claimed: str | None) -> None:
    """A user_id sent in the body/query must match the token (403 otherwise)."""
    if claimed is not None and claimed.strip() and claimed.strip() != token_user:
        raise HTTPException(status_code=403, detail="user_id does not match the authenticated user")
