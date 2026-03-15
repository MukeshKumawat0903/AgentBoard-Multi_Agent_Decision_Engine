"""
Shared FastAPI dependencies for AgentBoard.

Provides dependency injection for the LLM client,
debate storage, controller instances, and SSE event channels.
"""

from app.core.config import Settings, settings
from app.db.database import get_db as _get_db  # re-export for routes
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient, get_llm_client


# --- In-memory stores (V1) ---
# Both keyed by thread_id (str).  Swap for Redis/DB in production.
_debate_store: dict[str, DebateState] = {}
_decision_store: dict[str, FinalDecision] = {}

# SSE streaming – per thread_id list of asyncio.Queue objects that receive
# broadcast events from a running DebateController.
_event_queues: dict[str, list] = {}

# SSE replay buffer – ordered list of all events emitted for a thread so that
# late-joining SSE clients can replay history before switching to live events.
_event_replays: dict[str, list] = {}


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


def get_settings() -> Settings:
    """FastAPI dependency – returns application settings."""
    return settings


def get_groq_client() -> GroqClient:
    """FastAPI dependency – returns the singleton GroqClient."""
    return get_llm_client()


# Re-export DB dependency so routes only need to import from this module.
get_db = _get_db
