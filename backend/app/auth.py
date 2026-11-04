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


def set_shared_secret(secret: bytes) -> None:
    """Demo mode without AUTH_SECRET: a secret generated once and stored in the shared database,
    so every API replica (docker compose --scale api=2) and restart accepts the same tokens."""
    global _process_secret
    _process_secret = secret


def _secret() -> bytes:
    configured = os.getenv("AUTH_SECRET", "").strip()
    return configured.encode() if configured else _process_secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def demo_mode() -> bool:
    """DEMO_MODE=true (default for the challenge): public synthetic PINs and a user list on the
    login screen. false: customers need credentials from CUSTOMER_CREDENTIALS_FILE, the list is
    not served and AUTH_SECRET must be configured."""
    return os.getenv("DEMO_MODE", "true").strip().lower() == "true"


def _scrypt(secret: str, salt: str) -> str:
    return hashlib.scrypt(secret.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()


def _configured_credentials() -> dict:
    path = os.getenv("CUSTOMER_CREDENTIALS_FILE", "").strip()
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def verify_pin(user_id: str, pin: str) -> bool:
    if not demo_mode():
        cred = _configured_credentials().get(user_id)
        salt = cred["salt"] if cred else "00" * 16
        digest = _scrypt(str(pin), salt)  # computed for unknown users too (timing)
        return bool(cred) and hmac.compare_digest(digest, cred["hash"])
    user = DEMO_USERS.get(user_id)
    # compare_digest on both branches keeps timing independent of user existence.
    expected = user["pin"] if user else "\0" * 8
    return hmac.compare_digest(expected.encode(), str(pin).encode()) and user is not None


def check_production_settings() -> None:
    """Refuse to start outside demo mode without a signing secret or customer credentials."""
    if demo_mode():
        return
    if len(os.getenv("AUTH_SECRET", "").strip()) < 32:
        raise RuntimeError("DEMO_MODE=false requires AUTH_SECRET with at least 32 characters")
    if not _configured_credentials():
        raise RuntimeError("DEMO_MODE=false requires CUSTOMER_CREDENTIALS_FILE with hashed customer credentials")


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


ANONYMOUS = "anonymous"


def is_anonymous(user_id: str | None) -> bool:
    return not user_id or user_id == ANONYMOUS


def optional_user(authorization: str | None = Header(default=None)) -> str:
    """/api/chat: no Authorization header -> anonymous session (public knowledge, web, hand-off;
    customer-data tools answer login_required). A header that is present must be valid (401)."""
    if not authorization:
        return ANONYMOUS
    return require_user(authorization)


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


def main() -> int:
    """python -m app.auth add-customer <user_id> --file creds.json  (PIN read without echo)."""
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description=main.__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add-customer")
    add.add_argument("user_id")
    add.add_argument("--file", required=True)
    args = parser.parse_args()
    secret = getpass.getpass("PIN/password: ")
    if len(secret) < 6:
        raise SystemExit("use at least 6 characters outside demo mode")
    data = {}
    if os.path.exists(args.file):
        with open(args.file, encoding="utf-8") as fh:
            data = json.load(fh)
    salt = secrets.token_hex(16)
    data[args.user_id] = {"salt": salt, "hash": _scrypt(secret, salt)}
    with open(args.file, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(args.file, 0o600)
    print(f"customer {args.user_id} saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
