"""
AgentBoard – Multi-Agent Decision Engine

FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.api.routes import router
from app.utils.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError

logger = logging.getLogger("agentboard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "AgentBoard starting up",
        extra={
            "groq_model": settings.GROQ_MODEL,
            "max_rounds": settings.MAX_DEBATE_ROUNDS,
            "consensus_threshold": settings.CONSENSUS_THRESHOLD,
        },
    )
    yield
    logger.info("AgentBoard shutting down")


app = FastAPI(
    title="AgentBoard",
    description="Multi-Agent Decision Engine – AI agents debate, critique, and converge to structured decisions.",
    version="0.1.0",
    lifespan=lifespan,
)

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
        "version": "0.1.0",
        "groq_configured": bool(settings.GROQ_API_KEY),
    }
