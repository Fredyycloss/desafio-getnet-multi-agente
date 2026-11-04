from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from uuid import uuid4
import hmac

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .auth import DEMO_USERS, ensure_same_user, issue_token, require_user, verify_pin
from .infra.database import Database
from .infra.llm import LLMUnavailable, create_llm, resolve_provider_name
from .knowledge.ingest import load_documents
from .service import ChatService
from .agents.escalation_agent import HandoffUnavailable
from .language import detect_language
from .observability import current_timeline, finish_timeline, llm_budget_seconds, set_default_llm_budget, stage, start_timeline

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("getnet_assist")
state: dict = {"service": None, "db": None, "documents": [], "metrics": {"requests": 0, "chats": 0, "errors": 0, "total_latency_ms": 0}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = time.monotonic()
    db = Database()
    llm_required = os.getenv("OLLAMA_REQUIRED", "false").lower() == "true"
    llm = create_llm()
    llm_enabled = llm is not None
    if llm_required and not llm_enabled:
        raise RuntimeError("OLLAMA_REQUIRED=true requires a configured LLM provider")
    if llm is not None and hasattr(llm, "check_key") and os.getenv("ANTHROPIC_STARTUP_CHECK", "true").lower() == "true":
        # One minimal request so /api/health can say if the cloud key is refused or out of credit.
        llm.check_key()
    if llm is not None:
        set_default_llm_budget(llm.default_budget_seconds)
    if llm_required and llm and llm.provider == "ollama":
        timeout = float(os.getenv("OLLAMA_STARTUP_TIMEOUT_SECONDS", "900"))
        wait_started = time.monotonic()
        while True:
            llm_status = llm.health()
            if (
                llm_status.get("available")
                and llm_status.get("chat_model_loaded")
                and llm_status.get("embedding_model_loaded")
            ):
                break
            if time.monotonic() - wait_started >= timeout:
                raise RuntimeError(f"Required Ollama chat model did not become ready: {llm_status}")
            time.sleep(2)
    docs = load_documents()
    from .knowledge.ingest import load_snapshot_vectors
    vector_model, _, vectors = load_snapshot_vectors()
    service = ChatService(docs, db, llm, llm_required=llm_required, vectors=vectors, vector_model=vector_model)
    state.update({"service": service, "db": db, "documents": docs, "metrics": {"requests": 0, "chats": 0, "errors": 0, "total_latency_ms": 0}})
    logger.info("startup_complete docs=%d llm_provider=%s model=%s elapsed_ms=%d", len(docs),
                getattr(llm, "provider", "none"), getattr(llm, "model", None), int((time.monotonic()-started)*1000))
    yield
    db.close()


app = FastAPI(
    title="Getnet Assist — Agentic Multi-Agent Support",
    version="2.0.0",
    description="Supervisor-led multi-agent support with tool calling, persistent SQLite memory, hybrid RAG and public research tools.",
    lifespan=lifespan,
)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-Operator-Key", "X-Operator-ID"])


class HistoryMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    user_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=12)

    @field_validator("message")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip(): raise ValueError("message cannot be blank")
        return value.strip()

    @field_validator("user_id")
    @classmethod
    def safe_user_id(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value): raise ValueError("invalid user_id")
        return value


class TicketMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    user_id: str = Field(min_length=1, max_length=128)


class OperatorReply(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class OperatorResolution(BaseModel):
    resolution: str = Field(min_length=1, max_length=2000)


def require_operator(x_operator_key: str | None, x_operator_id: str | None) -> str:
    configured = os.getenv("OPERATOR_API_KEY", "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Operator API is disabled. Configure OPERATOR_API_KEY.")
    if not x_operator_key or not hmac.compare_digest(x_operator_key, configured):
        raise HTTPException(status_code=401, detail="Invalid operator credentials")
    operator_id = (x_operator_id or "").strip()
    if not operator_id or len(operator_id) > 80 or any(ord(c) < 32 for c in operator_id):
        raise HTTPException(status_code=400, detail="X-Operator-ID is required")
    return operator_id


@app.middleware("http")
async def observability(request: Request, call_next):
    trace_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.trace_id = trace_id
    start = time.monotonic()
    try:
        response = await call_next(request)
        state["metrics"]["requests"] += 1
        if response.status_code >= 500: state["metrics"]["errors"] += 1
        elapsed = int((time.monotonic()-start)*1000)
        state["metrics"]["total_latency_ms"] += elapsed
        response.headers["X-Request-ID"] = trace_id
        logger.info("http_request trace_id=%s method=%s path=%s status=%s latency_ms=%d", trace_id, request.method, request.url.path, response.status_code, elapsed)
        return response
    except Exception:
        state["metrics"]["errors"] += 1
        logger.exception("http_request_failed trace_id=%s path=%s", trace_id, request.url.path)
        raise


@app.get("/api/health")
def health():
    service = state.get("service")
    if not service: return {"status": "starting", "ready": False}
    llm_status = service.llm.health() if service.llm else {"available": False, "enabled": False}
    model_ready = bool(llm_status.get("available") and llm_status.get("chat_model_loaded"))
    return {"status": "ok", "ready": True, "service": "getnet-assist", "version": app.version,
            "knowledge_chunks": len(state["documents"]), "llm_enabled": bool(service.llm), "llm_available": model_ready, "llm": llm_status,
            "context_intelligence": service.llm.provider if service.llm else "deterministic_fallback",
            "llm_provider": service.llm.describe() if service.llm else {"provider": None},
            "cloud_status": {k: llm_status.get(k) for k in ("cloud_mode", "key_state", "message", "fallback_active", "fallback_reason")
                             if k in llm_status} or None,
            "llm_provider_setting": os.getenv("LLM_PROVIDER", "auto"),
            "request_llm_budget_seconds": llm_budget_seconds(),
            "llm_required": os.getenv("OLLAMA_REQUIRED", "false").lower() == "true",
            "supported_languages": ["pt", "en"], "database": "sqlite_persistent", "mode": "supervisor_tool_calling" if model_ready else "deterministic_fallback"}


@app.get("/api/agents")
def agents():
    return {"entry_agent": "ContextIntelligence", "supervisor": "SupervisorAgent",
        "message_flow": ["ContextIntelligence", "RiskAssessmentAgent", "human_priority_and_policy_gate", "SupervisorAgent", "specialist_agents", "CriticAgent_for_automated_drafts"],
        "specialists": [
        {"name": "KnowledgeAgent", "capabilities": ["BM25", "Ollama embeddings", "grounded generation"]},
        {"name": "CustomerSupportAgent", "tools": ["get_customer_profile", "get_terminal_status"]},
        {"name": "PaymentsAgent", "tools": ["lookup_payment_status", "find_declined_transactions"]},
        {"name": "WebResearchAgent", "tools": ["DuckDuckGo search", "Open-Meteo weather", "Frankfurter exchange rates"]},
        {"name": "RiskAssessmentAgent", "capabilities": ["safety preflight", "contextual hazard triage"]},
        {"name": "HumanEscalationAgent", "capabilities": ["persistent SQLite ticket queue", "protocol generation"]},
        {"name": "CriticAgent", "capabilities": ["language review", "evidence and safety review"]},
    ], "orchestration": "Ollama function-calling loop with bounded observe/re-plan; deterministic fallback is explicitly reported when LLM is disabled/unavailable."}


@app.get("/api/knowledge/sources")
def knowledge_sources():
    unique = {}
    for doc in state["documents"]:
        unique.setdefault(doc["url"], {"title": doc["title"], "url": doc["url"], "language": doc["language"], "source_type": doc["source_type"]})
    return {"document_chunks": len(state["documents"]), "unique_sources": len(unique), "sources": list(unique.values()), "boot_network_dependency": False}


class DemoLogin(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    pin: str = Field(min_length=1, max_length=16)


@app.get("/api/auth/demo-users")
def demo_users():
    """Synthetic demo merchants for the login screen (demonstration data only)."""
    return {"users": [{"user_id": uid, "merchant_name": item["merchant_name"], "demo_pin": item["pin"]}
                      for uid, item in DEMO_USERS.items()],
            "note": "Synthetic demo accounts. PINs are public on purpose; this is not production identity."}


@app.post("/api/auth/demo-login")
def demo_login(payload: DemoLogin):
    if not verify_pin(payload.user_id.strip(), payload.pin.strip()):
        raise HTTPException(status_code=401, detail="Invalid demo credentials")
    return issue_token(payload.user_id.strip())


@app.post("/api/chat")
def chat(payload: ChatRequest, request: Request, auth_user: str = Depends(require_user)):
    # Identity comes from the token; the body user_id is kept for the challenge contract and must match.
    ensure_same_user(auth_user, payload.user_id)
    service: ChatService | None = state.get("service")
    db: Database | None = state.get("db")
    if service is None or db is None: raise HTTPException(status_code=503, detail="Service is starting")
    trace_token = start_timeline(request.state.trace_id)
    session_id = payload.session_id or uuid4().hex
    try:
        with stage("session_read_and_validation", "persistence"):
            owner = db.get_session_owner(session_id)
            if owner is not None and owner != payload.user_id:
                # Do not reveal whether another merchant owns the session.
                raise HTTPException(status_code=404, detail="Session not found")
            try:
                db.ensure_session(session_id, payload.user_id)
            except PermissionError as exc:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            history = db.get_history(session_id, limit=12)
            if not history and payload.history:
                history = [item.model_dump() for item in payload.history[-10:]]
        from .agents.guardrails import inspect_message
        storage_guard = inspect_message(payload.message, detect_language(payload.message, history))
        stored_message = "[mensagem bloqueada por divulgação de dado sensível]" if storage_guard.get("blocked") else payload.message
        with stage("user_message_persistence", "persistence"):
            db.save_message(session_id, payload.user_id, "user", stored_message)
        result = service.answer(payload.message, payload.user_id, session_id, history, request.state.trace_id)
        with stage("assistant_message_persistence", "persistence"):
            db.save_message(session_id, payload.user_id, "assistant", result["answer"], result)
        timeline = current_timeline()
        result["stage_timings"] = timeline.snapshot() if timeline else []
        result["model_usage"] = timeline.model_usage() if timeline else {"llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0, "calls": []}
        db.record_stages(request.state.trace_id, result["stage_timings"])
        db.record_model_calls(request.state.trace_id, result["model_usage"]["calls"])
        state["metrics"]["chats"] += 1
        result["session_id"] = session_id
        logger.info("chat_done trace_id=%s session_id=%s intent=%s language=%s mode=%s tools=%s handoff=%s",
                    result["trace_id"], session_id, result["intent"], result["language"], result["orchestration_mode"], result["tool_calls"], result["handoff"])
        return result
    except LLMUnavailable as exc:
        db.record_stages(request.state.trace_id, getattr(exc, "stage_timings", current_timeline().snapshot() if current_timeline() else []))
        if current_timeline():
            db.record_model_calls(request.state.trace_id, current_timeline().model_calls)
        logger.error("chat_llm_unavailable trace_id=%s", request.state.trace_id)
        raise HTTPException(status_code=503, detail="Required local LLM is unavailable or returned an invalid response") from exc
    except HandoffUnavailable as exc:
        db.record_stages(request.state.trace_id, current_timeline().snapshot() if current_timeline() else [])
        logger.error("handoff_queue_unavailable trace_id=%s", request.state.trace_id)
        raise HTTPException(status_code=503, detail="The human-support request could not be confirmed. Please retry or use the official Getnet support channels.") from exc
    finally:
        finish_timeline(trace_token)


@app.get("/api/sessions/{session_id}/messages")
def session_messages(session_id: str, user_id: str | None = None, auth_user: str = Depends(require_user)):
    ensure_same_user(auth_user, user_id)
    db: Database | None = state.get("db")
    if not db: raise HTTPException(status_code=503, detail="Service is starting")
    if db.get_session_owner(session_id) != auth_user:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": db.get_history(session_id, 50)}


@app.get("/api/handoffs")
def list_handoffs(
    status: str | None = None,
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
    x_operator_id: str | None = Header(default=None, alias="X-Operator-ID"),
):
    # Queue-wide visibility is an operator capability, never a public endpoint.
    require_operator(x_operator_key, x_operator_id)
    service: ChatService | None = state.get("service")
    if not service: raise HTTPException(status_code=503, detail="Service is starting")
    items = service.handoff.list_tickets(status)
    return {"count": len(items), "items": items, "real_agent_connected": False, "environment": "demonstration"}


@app.get("/api/handoffs/{protocol}")
def get_handoff(protocol: str, user_id: str | None = None, auth_user: str = Depends(require_user)):
    ensure_same_user(auth_user, user_id)
    service: ChatService | None = state.get("service")
    if not service: raise HTTPException(status_code=503, detail="Service is starting")
    ticket = service.handoff.get_ticket(protocol)
    if not ticket or ticket.get("user_id") != auth_user:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return ticket


@app.post("/api/handoffs/{protocol}/messages")
def append_handoff_message(protocol: str, payload: TicketMessage, auth_user: str = Depends(require_user)):
    ensure_same_user(auth_user, payload.user_id)
    service: ChatService | None = state.get("service")
    if not service: raise HTTPException(status_code=503, detail="Service is starting")
    current = service.handoff.get_ticket(protocol)
    if not current or current.get("user_id") != payload.user_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    from .agents.guardrails import inspect_message
    language = detect_language(payload.message)
    guard = inspect_message(payload.message, language)
    if guard.get("blocked"): raise HTTPException(status_code=422, detail=guard["message"])
    try:
        ticket = service.handoff.append_customer_message(protocol, payload.message)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="The support queue is temporarily unavailable. Your update may not have been registered; retry or use the official Getnet support channels.") from exc
    if not ticket: raise HTTPException(status_code=404, detail="Protocol not found")
    if ticket.get("session_id"):
        service.db.save_message(ticket["session_id"], payload.user_id, "user", payload.message,
                                {"handoff_protocol": protocol})
        confirmation = "Sua atualização foi adicionada à solicitação registrada." if ticket.get("language") == "pt" else "Your update was added to the registered request."
        service.db.save_message(ticket["session_id"], payload.user_id, "assistant", confirmation,
                                {"handoff_protocol": protocol, "handoff_status": ticket.get("status")})
    return {"ticket": ticket, "message": "Added to simulated support queue; no live operator is connected."}


@app.get("/api/operator/queue")
def operator_queue(
    status: str | None = None,
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
    x_operator_id: str | None = Header(default=None, alias="X-Operator-ID"),
):
    require_operator(x_operator_key, x_operator_id)
    service: ChatService | None = state.get("service")
    if not service: raise HTTPException(status_code=503, detail="Service is starting")
    return {"count": len(service.handoff.list_tickets(status)), "items": service.handoff.list_tickets(status), "environment": "synthetic demonstration"}


@app.post("/api/operator/tickets/{protocol}/claim")
def operator_claim(
    protocol: str,
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
    x_operator_id: str | None = Header(default=None, alias="X-Operator-ID"),
):
    operator_id = require_operator(x_operator_key, x_operator_id)
    db: Database | None = state.get("db")
    if not db: raise HTTPException(status_code=503, detail="Service is starting")
    try:
        ticket = db.claim_ticket(protocol, operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ticket: raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ticket": ticket}


@app.post("/api/operator/tickets/{protocol}/messages")
def operator_reply(
    protocol: str,
    payload: OperatorReply,
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
    x_operator_id: str | None = Header(default=None, alias="X-Operator-ID"),
):
    operator_id = require_operator(x_operator_key, x_operator_id)
    db: Database | None = state.get("db")
    if not db: raise HTTPException(status_code=503, detail="Service is starting")
    try:
        ticket = db.append_operator_message(protocol, operator_id, payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ticket: raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ticket": ticket}


@app.post("/api/operator/tickets/{protocol}/resolve")
def operator_resolve(
    protocol: str,
    payload: OperatorResolution,
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
    x_operator_id: str | None = Header(default=None, alias="X-Operator-ID"),
):
    operator_id = require_operator(x_operator_key, x_operator_id)
    db: Database | None = state.get("db")
    if not db: raise HTTPException(status_code=503, detail="Service is starting")
    try:
        ticket = db.resolve_ticket(protocol, operator_id, payload.resolution)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ticket: raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ticket": ticket}


@app.get("/api/metrics")
def metrics():
    values = dict(state["metrics"])
    values["average_latency_ms"] = round(values["total_latency_ms"] / values["requests"], 2) if values["requests"] else 0
    db: Database | None = state.get("db")
    values["tools"] = db.get_tool_metrics() if db else {"calls": 0, "failures": 0, "by_tool": []}
    values["stages"] = db.get_stage_metrics() if db else {"calls": 0, "failures": 0, "timeouts": 0, "by_stage": []}
    values["model"] = db.get_model_metrics() if db else {"calls": 0, "requests_with_llm": 0, "by_purpose": []}
    return values
