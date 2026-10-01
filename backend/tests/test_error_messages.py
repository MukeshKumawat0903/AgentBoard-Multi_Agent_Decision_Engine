"""
Errors shown to users must not leak raw provider/internal exception text
(organisation IDs, request payloads, file paths). The full exception is logged
server-side; SSE error events and resume failures carry a safe message plus the
error type so the UI can map it.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from app.api.routes import _event_writer_loop, _run_debate_background
from app.core.config import settings
from app.db.crud import get_debate_events
from app.schemas.state import DebateState
from app.utils.exceptions import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
    public_error_message,
)

SECRET = "Rate limit reached for model `x` in organization `org_01kv0d99vrfbvsqm25qrhagq3q`"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (LLMResponseError(SECRET), "The AI model failed to produce a valid response."),
        (LLMConnectionError(SECRET), "Could not connect to the AI provider."),
        (LLMRateLimitError(SECRET), "rate-limited"),
        (RuntimeError(SECRET), "unexpected error"),
    ],
)
def test_public_message_hides_exception_text(exc, expected):
    message = public_error_message(exc)
    assert expected in message
    assert "org_01kv" not in message


@pytest.mark.anyio
async def test_background_failure_event_is_sanitised_but_typed():
    state = DebateState(user_query="Which vendor should we pick for the rollout?", status="in_progress")
    queues: dict = {state.thread_id: []}
    replays: dict = {state.thread_id: []}
    persist_queue: asyncio.Queue = asyncio.Queue()
    writer = asyncio.create_task(
        _event_writer_loop(persist_queue, queues[state.thread_id], replays[state.thread_id],
                           state.thread_id, settings.DATABASE_URL)
    )
    graph = MagicMock()
    graph.run = AsyncMock(side_effect=LLMResponseError(f"Structured output failed via groq: {SECRET}"))

    await _run_debate_background(
        graph, state, {}, {}, queues, replays, settings.DATABASE_URL,
        persist_queue=persist_queue, writer_task=writer,
    )

    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        events = await get_debate_events(db, state.thread_id)
    error = next(e for e in events if e["type"] == "error")
    assert error["error_type"] == "LLMResponseError"
    assert error["detail"] == "The AI model failed to produce a valid response."
    assert "org_01kv" not in str(error)
