"""
Shared FastAPI dependencies for AgentBoard.

Provides dependency injection for the LLM client,
debate storage, and controller instances.
"""

from app.core.config import Settings, settings
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient, get_llm_client


# --- In-memory stores (V1) ---
# Both keyed by thread_id (str).  Swap for Redis/DB in production.
_debate_store: dict[str, DebateState] = {}
_decision_store: dict[str, FinalDecision] = {}


def get_debate_store() -> dict[str, DebateState]:
    """FastAPI dependency – returns the in-memory debate-state store."""
    return _debate_store


def get_decision_store() -> dict[str, FinalDecision]:
    """FastAPI dependency – returns the in-memory final-decision store."""
    return _decision_store


def get_settings() -> Settings:
    """FastAPI dependency – returns application settings."""
    return settings


def get_groq_client() -> GroqClient:
    """FastAPI dependency – returns the singleton GroqClient."""
    return get_llm_client()
