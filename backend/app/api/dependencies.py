"""
Shared FastAPI dependencies for AgentBoard.

Provides dependency injection for the LLM client, in-memory stores,
background task registry, and SSE event channels.
"""

import asyncio

from app.core.config import Settings, settings
from app.db.database import get_db as _get_db  # re-export for routes
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import LangChainProvider, get_llm_client


# --- In-memory stores (V1) ---
# Both keyed by thread_id (str).  Swap for Redis/DB in production.
_debate_store: dict[str, DebateState] = {}
_decision_store: dict[str, FinalDecision] = {}

# Per-thread asyncio locks – prevent concurrent mutation of the same debate
# state from a background task and an SSE handler running in the same loop.
_thread_locks: dict[str, asyncio.Lock] = {}


def get_thread_lock(thread_id: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock for a given thread_id."""
    if thread_id not in _thread_locks:
        _thread_locks[thread_id] = asyncio.Lock()
    return _thread_locks[thread_id]

# SSE streaming – per thread_id list of asyncio.Queue objects that receive
# broadcast events from a running DebateController.
_event_queues: dict[str, list] = {}

# SSE replay buffer – ordered list of all events emitted for a thread so that
# late-joining SSE clients can replay history before switching to live events.
_event_replays: dict[str, list] = {}

# Background task registry for async debates. Presence means the thread
# is actively executing in this process.
_background_tasks: dict[str, asyncio.Task] = {}


def get_debate_store() -> dict[str, DebateState]:
    """FastAPI dependency – returns the in-memory debate-state store."""
    return _debate_store


def get_decision_store() -> dict[str, FinalDecision]:
    """FastAPI dependency – returns the in-memory final-decision store."""
    return _decision_store


def get_event_queues() -> dict[str, list]:
    """FastAPI dependency – returns the per-thread SSE queue registry."""
    return _event_queues


def get_event_replays() -> dict[str, list]:
    """FastAPI dependency – returns the per-thread SSE replay buffer registry."""
    return _event_replays


def get_background_tasks() -> dict[str, asyncio.Task]:
    """FastAPI dependency – returns the active async debate task registry."""
    return _background_tasks


def get_settings() -> Settings:
    """FastAPI dependency – returns application settings."""
    return settings


def get_groq_client() -> LangChainProvider:
    """FastAPI dependency – returns the singleton LangChainProvider."""
    return get_llm_client()


# Re-export DB dependency so routes only need to import from this module.
get_db = _get_db


# ---------------------------------------------------------------------------
# P3 – Knowledge base + agent memory singletons
# These are populated by main.py's lifespan before the first request.
# ---------------------------------------------------------------------------

_knowledge_base = None   # KnowledgeBase | None
_memory_store = None     # AgentMemoryStore | None


def set_knowledge_base(kb) -> None:
    """Set the application-level KnowledgeBase singleton (called from lifespan)."""
    global _knowledge_base
    _knowledge_base = kb


def get_knowledge_base():
    """Return the KnowledgeBase singleton, or a no-op stub if not initialised."""
    if _knowledge_base is None:
        from app.services.retriever import KnowledgeBase
        return KnowledgeBase(
            persist_dir=settings.KNOWLEDGE_BASE_DIR,
            embedding_model=settings.KB_EMBEDDING_MODEL,
            chunk_size=settings.KB_CHUNK_SIZE,
            chunk_overlap=settings.KB_CHUNK_OVERLAP,
            similarity_threshold=settings.KB_SIMILARITY_THRESHOLD,
            top_k=settings.KB_TOP_K,
        )
    return _knowledge_base


def set_memory_store(ms) -> None:
    """Set the application-level AgentMemoryStore singleton (called from lifespan)."""
    global _memory_store
    _memory_store = ms


def get_memory_store():
    """Return the AgentMemoryStore singleton, or None if not initialised."""
    return _memory_store
