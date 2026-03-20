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
import uuid
from contextlib import asynccontextmanager
from typing import cast

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
from app.core.rate_limiter import limiter
from app.api.routes import router
from app.db.database import init_db
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
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging(settings.LOG_LEVEL)

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

    await init_db()
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
    version="0.2.0",
    lifespan=lifespan,
)

# --- Rate Limiter (Phase 5) ---
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    cast(ExceptionHandler, _rate_limit_exceeded_handler),
)
app.add_middleware(SlowAPIMiddleware)

# --- Request-ID Middleware (Phase 5) ---
app.add_middleware(RequestIDMiddleware)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Include API Router ---
app.include_router(router)


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
