from __future__ import annotations
import logging, os, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from .knowledge.ingest import load_documents
from .service import ChatService

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("getnet_assist")
state: dict = {"service": None, "documents": []}

@asynccontextmanager
async def lifespan(app: FastAPI):
    started = time.monotonic()
    docs = load_documents()
    state["documents"] = docs
    state["service"] = ChatService(docs)
    logger.info("knowledge_loaded chunks=%d elapsed_ms=%d", len(docs), int((time.monotonic()-started)*1000))
    yield

app = FastAPI(title="Getnet Assist — Multi-Agent API", version="1.0.0", description="API demonstrativa de orquestração multiagente com RAG.", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    user_id: str = Field(default="anonymous", min_length=1, max_length=128)
    @field_validator("message")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A mensagem não pode estar vazia.")
        return value.strip()

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    logger.info("request method=%s path=%s status=%s elapsed_ms=%d", request.method, request.url.path, response.status_code, int((time.monotonic()-start)*1000))
    return response

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "getnet-assist", "knowledge_chunks": len(state["documents"]), "llm_enabled": os.getenv("OLLAMA_ENABLED", "false").lower() == "true"}

@app.get("/api/knowledge/sources")
def sources():
    unique = {}
    for doc in state["documents"]:
        unique[doc["url"]] = {"title": doc["title"], "url": doc["url"]}
    return {"count": len(state["documents"]), "sources": list(unique.values())}

@app.post("/api/chat")
def chat(payload: ChatRequest):
    service = state.get("service")
    if service is None:
        raise HTTPException(status_code=503, detail="Serviço ainda está inicializando.")
    started = time.monotonic()
    result = service.answer(payload.message, payload.user_id)
    logger.info("chat_completed agent=%s intent=%s confidence=%.2f handoff=%s elapsed_ms=%d", result["agent"], result["intent"], result["confidence"], result["handoff"], int((time.monotonic()-started)*1000))
    return result
