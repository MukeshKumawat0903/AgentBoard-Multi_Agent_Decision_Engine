"""
Shared pytest fixtures for AgentBoard tests.

Provides reusable test infrastructure: mock LLM client,
sample debate state, sample agent response, etc.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.agent_response import AgentResponse
from app.schemas.state import DebateState


@pytest.fixture
def anyio_backend():
    """Use asyncio as the async backend for tests."""
    return "asyncio"


@pytest.fixture
def mock_llm_client():
    """Returns a GroqClient stand-in with mocked chat_json and chat methods."""
    client = MagicMock()
    client.chat = AsyncMock(return_value="Mocked LLM response text.")
    client.chat_json = AsyncMock(
        return_value={
            "position": "Proceed with the initiative carefully.",
            "reasoning": "Data supports a measured approach.",
            "assumptions": ["Stable macro environment"],
            "confidence_score": 0.78,
        }
    )
    return client


@pytest.fixture
def sample_agent_response():
    """Returns a valid, fully populated AgentResponse for use in tests."""
    return AgentResponse(
        agent_name="Analyst",
        round_number=1,
        position="Strong demand signals in SE Asia.",
        reasoning="Market data confirms growth trajectory.",
        assumptions=["Stable regulatory environment", "Currency risks hedged"],
        confidence_score=0.85,
    )


@pytest.fixture
def sample_debate_state():
    """Returns a pre-populated DebateState suitable for orchestrator tests."""
    state = DebateState(
        user_query="Should our company expand into the Asian market in Q3?",
        current_round=1,
        max_rounds=4,
    )
    return state
