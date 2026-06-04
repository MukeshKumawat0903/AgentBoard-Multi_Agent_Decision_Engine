"""
AgentBoard – Multi-Agent Decision Engine

FastAPI application entry point.

Phase 5 additions
-----------------
- LangSmith tracing: configured at startup via env vars when
  ``settings.LANGSMITH_TRACING`` is True.
- RequestIDMiddleware: stamps every response with ``X-Request-ID``
  (reads client header, or generates a UUID if absent).  Enables
  distributed log correlation.
- SlowAPI rate limiting: IP-based rate limiting via ``slowapi`` with
  a MemoryStorage backend (swap for Redis in multi-instance deploys).
"""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import cast

import aiosqlite

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler  # type: ignore[import-untyped]
from slowapi.errors import RateLimitExceeded  # type: ignore[import-untyped]
from slowapi.middleware import SlowAPIMiddleware  # type: ignore[import-untyped]
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ExceptionHandler

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.metrics import app_metrics
from app.core.rate_limiter import limiter
from app.core.request_context import reset_request_id, set_request_id
from app.api.routes import router
from app.api.analytics import router as analytics_router
from app.db.database import run_migrations
from app.db.crud import cleanup_old_debates
from app.agents.registry import registry, AgentConfig
from app.agents.analyst_agent import AnalystAgent, SYSTEM_PROMPT as ANALYST_PROMPT
from app.agents.risk_agent import RiskAgent, SYSTEM_PROMPT as RISK_PROMPT
from app.agents.strategy_agent import StrategyAgent, SYSTEM_PROMPT as STRATEGY_PROMPT
from app.agents.ethics_agent import EthicsAgent, SYSTEM_PROMPT as ETHICS_PROMPT
from app.agents.moderator_agent import ModeratorAgent, SYNTHESIS_SYSTEM_PROMPT as MODERATOR_PROMPT
from app.agents.domain_agents import (
    FinancialEthicsAgent,
    SecurityAgent,
    ComplianceAgent,
    PatientSafetyAgent,
)
from app.utils.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError

logger = logging.getLogger("agentboard")


# ---------------------------------------------------------------------------
# Request-ID middleware — stamps X-Request-ID on every response
# ---------------------------------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Injects a ``X-Request-ID`` header on every response.

    If the client sends ``X-Request-ID``, the same value is echoed back.
    Otherwise a fresh UUID4 is generated.  This enables end-to-end log
    correlation between client, gateway, and backend log lines.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            app_metrics.record_request(request.method, route_path, response.status_code, duration_ms)
            logger.info(
                "http_request_completed",
                extra={
                    "method": request.method,
                    "path": route_path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else None,
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_request_id(token)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging(settings.LOG_LEVEL)
    app_metrics.reset()

    # Phase 5: initialise LangSmith tracing before any LangChain calls
    if settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.LANGSMITH_API_KEY)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.LANGSMITH_PROJECT)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.LANGSMITH_ENDPOINT)
        logger.info(
            "LangSmith tracing enabled",
            extra={"project": settings.LANGSMITH_PROJECT},
        )

    run_migrations()
    # TTL cleanup: remove debates older than configured threshold
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await cleanup_old_debates(db, settings.DEBATE_TTL_DAYS)

    # P3: Initialise knowledge base and agent memory singletons
    from app.services.retriever import KnowledgeBase
    from app.services.agent_memory import AgentMemoryStore
    from app.services.llm_client import get_llm_client
    from app.api.dependencies import set_knowledge_base, set_memory_store

    kb = KnowledgeBase(
        persist_dir=settings.KNOWLEDGE_BASE_DIR,
        embedding_model=settings.KB_EMBEDDING_MODEL,
        chunk_size=settings.KB_CHUNK_SIZE,
        chunk_overlap=settings.KB_CHUNK_OVERLAP,
        similarity_threshold=settings.KB_SIMILARITY_THRESHOLD,
        top_k=settings.KB_TOP_K,
    )
    set_knowledge_base(kb)
    # R8: warm model in background thread to avoid blocking the event loop on first request
    if kb.is_available:
        await kb.warm()
    logger.info("knowledge_base_initialized", extra={"available": kb.is_available})

    ms = AgentMemoryStore(
        database_url=settings.DATABASE_URL,
        llm_client=get_llm_client(),
    )
    set_memory_store(ms)
    logger.info("agent_memory_store_initialized")

    # Agent registry: register all built-in agents
    _enabled = {n.strip() for n in settings.ENABLED_AGENTS.split(",")}
    _agent_defs = [
        (AnalystAgent,  "Analyst",  "Objective data analyst",           "📊", ANALYST_PROMPT),
        (RiskAgent,     "Risk",     "Risk identification and assessment","⚠️",  RISK_PROMPT),
        (StrategyAgent, "Strategy", "Strategic planning and options",    "🎯", STRATEGY_PROMPT),
        (EthicsAgent,   "Ethics",   "Ethical impact evaluator",         "🤝", ETHICS_PROMPT),
        (ModeratorAgent,"Moderator","Debate moderator and synthesizer",  "🏛️", MODERATOR_PROMPT),
    ]
    # P3.2: Tools enabled per-agent. Analyst uses web_search + date for factual grounding;
    # Strategy uses date for time-sensitive reasoning. Others stay tool-free by default.
    _agent_tools: dict[str, list[str]] = {
        "Analyst":  ["web_search", "get_current_date"],
        "Strategy": ["get_current_date"],
    }
    for agent_cls, name, role, icon, prompt in _agent_defs:
        registry.register(
            agent_class=agent_cls,
            config=AgentConfig(
                name=name,
                role=role,
                icon=icon,
                system_prompt=prompt,
                enabled=(name in _enabled),
                allowed_tools=_agent_tools.get(name, []),
            ),
        )

    # P3.4: Register domain agents (disabled by default; activated via domain_pack selector)
    _domain_defs = [
        (FinancialEthicsAgent, "FinancialEthics", "Fiduciary & ESG ethics evaluator",  "💰"),
        (SecurityAgent,        "Security",        "Cybersecurity & attack surface",     "🔒"),
        (ComplianceAgent,      "Compliance",      "Regulatory & legal compliance",      "📋"),
        (PatientSafetyAgent,   "PatientSafety",   "Clinical risk & patient welfare",    "🏥"),
    ]
    for agent_cls, name, role, icon in _domain_defs:
        registry.register(
            agent_class=agent_cls,
            config=AgentConfig(
                name=name,
                role=role,
                icon=icon,
                system_prompt="",   # domain agents store their prompt internally
                enabled=False,      # always off globally; activated per-debate via domain_pack
            ),
        )
    logger.info(
        "agent_registry_initialized",
        extra={"enabled": registry.enabled_agents()},
    )

    logger.info(
        "AgentBoard starting up",
        extra={
            "provider": settings.LLM_PROVIDER,
            "groq_model": settings.GROQ_MODEL,
            "max_rounds": settings.MAX_DEBATE_ROUNDS,
            "consensus_threshold": settings.CONSENSUS_THRESHOLD,
            "semantic_consensus": settings.SEMANTIC_CONSENSUS_ENABLED,
        },
    )
    yield
    logger.info("AgentBoard shutting down")


app = FastAPI(
    title="AgentBoard",
    description="Multi-Agent Decision Engine – AI agents debate, critique, and converge to structured decisions.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    app_metrics.increment_event("rate_limit_exceeded")
    logger.warning(
        "rate_limit_exceeded",
        extra={
            "method": request.method,
            "path": route_path,
            "client_ip": request.client.host if request.client else None,
        },
    )
    return _rate_limit_exceeded_handler(request, exc)

# --- Rate Limiter (Phase 5) ---
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    cast(ExceptionHandler, rate_limit_exceeded_handler),
)
app.add_middleware(SlowAPIMiddleware)

# --- Request-ID Middleware (Phase 5) ---
app.add_middleware(RequestIDMiddleware)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "Last-Event-ID"],
)

# --- Include API Routers ---
app.include_router(router)
app.include_router(analytics_router)


# --- Exception Handlers ---

@app.exception_handler(LLMResponseError)
async def llm_response_error_handler(request: Request, exc: LLMResponseError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "llm_response_error", "detail": str(exc)},
    )


@app.exception_handler(LLMConnectionError)
async def llm_connection_error_handler(request: Request, exc: LLMConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "llm_connection_error", "detail": str(exc)},
    )


@app.exception_handler(LLMRateLimitError)
async def llm_rate_limit_error_handler(request: Request, exc: LLMRateLimitError) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "llm_rate_limit", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": "An unexpected error occurred."},
    )


# --- Health Check ---
@app.get("/health", tags=["system"])
async def health_check():
    """Health check endpoint for monitoring and container probes."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "groq_configured": bool(settings.GROQ_API_KEY),
    }
