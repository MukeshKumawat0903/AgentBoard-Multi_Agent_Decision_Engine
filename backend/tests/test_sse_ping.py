"""
Quiet SSE connections (long LLM phases, HITL pauses) must carry a *named*
`ping` event: EventSource never surfaces comment lines, so a comment
keep-alive cannot stop the browser's stale-connection timer.
"""

import asyncio

import aiosqlite
import pytest
from starlette.requests import Request

import app.api.routes as routes
from app.core.config import settings
from app.schemas.state import DebateState


def _never_disconnecting_request() -> Request:
    async def receive():
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
    return Request(scope, receive)


@pytest.mark.anyio
async def test_quiet_stream_sends_named_ping_events(monkeypatch):
    monkeypatch.setattr(routes, "_SSE_KEEPALIVE_SECONDS", 0.05)
    paused = DebateState(user_query="Which vendor should we pick?", status="awaiting_approval")

    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        response = await routes.stream_debate_events(
            paused.thread_id,
            _never_disconnecting_request(),
            debate_store={paused.thread_id: paused},
            decision_store={},
            background_tasks={},
            active_runs=set(),
            all_queues={},
            all_replays={},
            db=db,
        )
        frames = response.body_iterator
        try:
            first = await asyncio.wait_for(frames.__anext__(), timeout=5)
            second = await asyncio.wait_for(frames.__anext__(), timeout=5)
        finally:
            await frames.aclose()

    assert first == "event: ping\ndata: {}\n\n"
    assert second == "event: ping\ndata: {}\n\n"


async def _drain(response, limit: int = 10) -> list[str]:
    """Collect frames until the generator ends (or ``limit`` frames, as a guard)."""
    frames, out = response.body_iterator, []
    try:
        while len(out) < limit:
            out.append(await asyncio.wait_for(frames.__anext__(), timeout=5))
    except StopAsyncIteration:
        pass
    finally:
        await frames.aclose()
    return out


async def _open_stream(db, state: DebateState, all_queues: dict, **overrides):
    kwargs = dict(
        debate_store={state.thread_id: state},
        decision_store={},
        background_tasks={},
        active_runs=set(),
        all_queues=all_queues,
        all_replays={},
        db=db,
    )
    kwargs.update(overrides)
    return await routes.stream_debate_events(state.thread_id, _never_disconnecting_request(), **kwargs)


@pytest.mark.anyio
async def test_stream_ends_after_replaying_a_terminal_event(monkeypatch):
    from app.db.crud import save_debate_event

    monkeypatch.setattr(routes, "_SSE_KEEPALIVE_SECONDS", 0.05)
    failed = DebateState(user_query="Which vendor should we pick?", status="error")
    all_queues: dict = {}
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await save_debate_event(db, failed.thread_id, {"type": "error", "detail": "boom"})
        frames = await _drain(await _open_stream(db, failed, all_queues))

    assert len(frames) == 1 and frames[0].startswith("id: 1\nevent: error\n")
    assert failed.thread_id not in all_queues  # no leftover subscriber list


@pytest.mark.anyio
async def test_finished_debate_without_a_decision_reports_it_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(routes, "_SSE_KEEPALIVE_SECONDS", 0.05)
    finished = DebateState(user_query="Which vendor should we pick?", status="converged")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        frames = await _drain(await _open_stream(db, finished, {}))

    assert len(frames) == 1
    assert frames[0].startswith("event: error\n") and "decision_unavailable" in frames[0]


@pytest.mark.anyio
async def test_paused_debate_stream_stays_open_and_keeps_its_subscriber_list(monkeypatch):
    monkeypatch.setattr(routes, "_SSE_KEEPALIVE_SECONDS", 0.05)
    paused = DebateState(user_query="Which vendor should we pick?", status="awaiting_approval")
    all_queues: dict = {}
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        frames = await _drain(await _open_stream(db, paused, all_queues), limit=3)

    assert frames == ["event: ping\ndata: {}\n\n"] * 3
    assert paused.thread_id in all_queues  # the approval continuation will broadcast here
