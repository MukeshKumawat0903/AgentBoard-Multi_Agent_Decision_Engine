"""
Shared pytest fixtures for AgentBoard tests.

Provides reusable test infrastructure: mock LLM client,
sample debate state, sample agent response, etc.

Every test runs against its own migrated SQLite file, checkpoint file and
knowledge-base directory under ``tmp_path``, so the suite never reads from or
writes to the developer's real ``agentboard.db``.
"""

import logging
import os
import shutil
from unittest.mock import AsyncMock, MagicMock

import pytest

# Tests must never need (or use) a real provider key. Set a dummy one before
# the settings singleton is created so the suite also runs without a .env file.
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from app.schemas.agent_response import AgentResponse  # noqa: E402
from app.schemas.state import DebateState  # noqa: E402


@pytest.fixture(scope="session")
def _migrated_db_template(tmp_path_factory):
    """Run the Alembic migrations once per session into a template database."""
    from app.core.config import settings
    from app.db.database import run_migrations

    template = tmp_path_factory.mktemp("db_template") / "agentboard.db"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "DATABASE_URL", str(template))
        run_migrations()
    return template


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch, _migrated_db_template):
    """Point all persistence paths at a fresh per-test copy of the migrated database."""
    from app.core.config import settings

    db_path = tmp_path / "agentboard.db"
    shutil.copyfile(_migrated_db_template, db_path)
    monkeypatch.setattr(settings, "DATABASE_URL", str(db_path))
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_URL", str(tmp_path / "checkpoints.db"))
    monkeypatch.setattr(settings, "KNOWLEDGE_BASE_DIR", str(tmp_path / "knowledge_base"))
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path / "logs"))
    yield
    # A test that ran the app lifespan attached a file handler inside tmp_path;
    # release it so later tests don't keep logging into a stale temp file.
    app_logger = logging.getLogger("agentboard")
    for handler in list(app_logger.handlers):
        if isinstance(handler, logging.FileHandler) and str(tmp_path) in handler.baseFilename:
            handler.close()
            app_logger.removeHandler(handler)


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
