"""Operator API (web console) and resumption helpers.

Every operator action requires an individual operator token (POST /api/operator/login);
the shared X-Operator-Key exists only for bootstrap when OPERATOR_API_KEY is set
(disabled by default). All actions are audited per operator.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import issue_operator_token, verify_claims
from . import operators as ops

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/operator", tags=["operator"])


def _state():
    from ..main import state  # late import: main owns the application state
    return state


class OperatorLogin(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class OperatorText(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class Resolution(BaseModel):
    resolution: str = Field(min_length=1, max_length=2000)


class Instruction(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


def require_operator(authorization: str | None = Header(default=None),
                     x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
                     x_operator_id: str | None = Header(default=None, alias="X-Operator-ID")) -> dict:
    db = _state()["db"]
    scheme, _, token = (authorization or "").partition(" ")
    claims = verify_claims(token.strip()) if scheme.lower() == "bearer" and token else None
    if claims and claims.get("kind") == "operator":
        username = str(claims["sub"]).removeprefix("op:")
        op = ops.get_operator(db, username)
        if not op or not op["active"]:
            raise HTTPException(status_code=401, detail="Operator disabled")
        ops.heartbeat(db, f"console:{username}")
        return {"username": username, "display_name": op["display_name"], "role": op["role"]}
    bootstrap = os.getenv("OPERATOR_API_KEY", "").strip()
    if bootstrap and x_operator_key and hmac.compare_digest(x_operator_key, bootstrap):
        operator_id = (x_operator_id or "").strip()
        if not operator_id or len(operator_id) > 80 or any(ord(c) < 32 for c in operator_id):
            raise HTTPException(status_code=400, detail="X-Operator-ID is required")
        return {"username": f"key:{operator_id}", "display_name": operator_id, "role": "operator"}
    raise HTTPException(status_code=401, detail="Operator authentication required: POST /api/operator/login")


def require_supervisor(operator: dict = Depends(require_operator)) -> dict:
    if operator["role"] != "supervisor":
        raise HTTPException(status_code=403, detail="Supervisor role required")
    return operator


@router.post("/login")
def operator_login(payload: OperatorLogin, request: Request):
    db = _state()["db"]
    limiter = _state().get("login_limiter")
    key = f"op:{payload.username}:{request.client.host if request.client else '-'}"
    if limiter and not limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many attempts", headers={"Retry-After": str(limiter.retry_after(key))})
    op = ops.verify_operator(db, payload.username.strip(), payload.password)
    if not op:
        if limiter:
            limiter.fail(key)
        ops.audit(db, payload.username[:80], "console", "login", None, "failed")
        raise HTTPException(status_code=401, detail="Invalid operator credentials")
    if limiter:
        limiter.success(key)
    ops.audit(db, op["username"], "console", "login", None, "ok")
    return issue_operator_token(op)


def _hitl():
    service = _state()["service"]
    if service is None:
        raise HTTPException(status_code=503, detail="Service is starting")
    return service.hitl


@router.get("/queue")
def operator_queue(status: str | None = None, operator: dict = Depends(require_operator)):
    hitl = _hitl()
    items = hitl.db.list_tickets(status)
    if status is None:  # active work first; resolved tickets stay out of the default view
        items = [t for t in items if t["status"] in {"queued", "assigned"}]
    return {"count": len(items), "items": items, **hitl.channel_status()}


@router.get("/tickets/{protocol}")
def operator_ticket(protocol: str, operator: dict = Depends(require_operator)):
    ticket = _hitl().db.get_ticket(protocol)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _act(fn, *args):
    try:
        ticket = fn(*args)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ticket": ticket}


@router.post("/tickets/{protocol}/claim")
def operator_claim(protocol: str, operator: dict = Depends(require_operator)):
    hitl = _hitl()
    if not hitl.db.get_ticket(protocol):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _act(hitl.claim, protocol.upper(), operator, "console")


@router.post("/tickets/{protocol}/messages")
def operator_reply(protocol: str, payload: OperatorText, operator: dict = Depends(require_operator)):
    hitl = _hitl()
    if not hitl.db.get_ticket(protocol):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _act(hitl.reply, protocol.upper(), operator, payload.message, "console")


@router.post("/tickets/{protocol}/resolve")
def operator_resolve(protocol: str, payload: Resolution, operator: dict = Depends(require_operator)):
    hitl = _hitl()
    if not hitl.db.get_ticket(protocol):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _act(hitl.resolve, protocol.upper(), operator, payload.resolution, "console")


@router.post("/tickets/{protocol}/return-to-ai")
def operator_return_to_ai(protocol: str, payload: Instruction, operator: dict = Depends(require_operator)):
    hitl = _hitl()
    if not hitl.db.get_ticket(protocol):
        raise HTTPException(status_code=404, detail="Ticket not found")
    result = _act(hitl.return_to_ai, protocol.upper(), operator, payload.instruction, "console")
    resumed = resume_if_pending(result["ticket"])
    return {**result, "resumed": resumed is not None}


@router.get("/audit")
def operator_audit(limit: int = 100, operator: dict = Depends(require_supervisor)):
    return {"items": ops.list_audit(_hitl().db, min(max(limit, 1), 500))}


@router.get("/channels")
def operator_channels(operator: dict = Depends(require_operator)):
    return _hitl().channel_status()


def resume_if_pending(ticket: dict | None) -> dict | None:
    """After "return to AI": the Supervisor answers the customer's pending request with the
    operator instruction in the history (author assistant_resume). Runs once per ticket."""
    state = _state()
    service, db = state["service"], state["db"]
    if not ticket or not ticket.get("resume_pending") or not ticket.get("session_id"):
        return None
    db.set_ticket_fields(ticket["protocol"], resume_pending=0)
    pending = next((m["content"] for m in reversed(ticket.get("messages", [])) if m["role"] == "user"), None)
    if not pending:
        return None
    history = db.get_history(ticket["session_id"], limit=12)
    try:
        result = service.answer(pending, ticket["user_id"], ticket["session_id"], history)
    except Exception as exc:  # noqa: BLE001 - resumption failure must not break the operator action
        logger.warning("resume_failed protocol=%s error=%s", ticket["protocol"], type(exc).__name__)
        return None
    result["trace"] = ["resumed_after_human_handoff", *result.get("trace", [])]
    db.save_message(ticket["session_id"], ticket["user_id"], "assistant", result["answer"],
                    {**{k: result[k] for k in ("trace", "sources", "critic", "agent") if k in result},
                     "author": "assistant_resume", "handoff_protocol": ticket["protocol"]})
    return result
