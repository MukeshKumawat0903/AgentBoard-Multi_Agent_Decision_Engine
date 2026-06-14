"""
BUG-18 — terminal-state cleanup of in-memory SSE replay buffers/queues/locks.

_run_debate_background must drop a finished debate's entries from
all_queues / all_replays / the per-thread lock once it reaches a terminal
state (completed/cancelled/error), since debate_events/decisions in SQLite
fully cover reconnect replay from that point on (BUG-14). A debate paused
for HITL approval (awaiting_approval) is not terminal and must keep its
entries so /debate/{id}/approve can find them.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.api.dependencies import get_thread_lock
from app.api.routes import _event_writer_loop, _run_debate_background
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


def _make_state(thread_id: str, **kwargs) -> DebateState:
    defaults = dict(
        thread_id=thread_id,
        user_query="Should we expand into the Asian market in Q3?",
        current_round=2,
        status="converged",
        agreement_score=0.85,
    )
    return DebateState(**{**defaults, **kwargs})


def _make_decision(thread_id: str) -> FinalDecision:
    return FinalDecision(
        thread_id=thread_id,
        decision="Proceed with phased expansion.",
        rationale_summary="Consensus after 2 rounds.",
        confidence_score=0.87,
        agreement_score=0.85,
        total_rounds=2,
        termination_reason="consensus_reached",
    )


def _mock_graph(state: DebateState, decision: FinalDecision | None) -> MagicMock:
    g = MagicMock()
    g.run = AsyncMock(return_value=(state, decision))
    return g


def _start_writer(all_queues: dict, all_replays: dict, thread_id: str) -> tuple[asyncio.Queue, asyncio.Task]:
    persist_queue: asyncio.Queue = asyncio.Queue()
    writer_task = asyncio.create_task(
        _event_writer_loop(
            persist_queue, all_queues[thread_id], all_replays[thread_id], thread_id, ":memory:"
        )
    )
    return persist_queue, writer_task


class TestTerminalThreadCleanup:

    @pytest.mark.anyio
    async def test_completed_debate_drops_replay_buffer_queue_and_lock(self):
        thread_id = str(uuid4())
        state = _make_state(thread_id)
        decision = _make_decision(thread_id)

        all_queues: dict = {thread_id: []}
        all_replays: dict = {thread_id: []}
        lock_before = get_thread_lock(thread_id)
        persist_queue, writer_task = _start_writer(all_queues, all_replays, thread_id)

        await _run_debate_background(
            _mock_graph(state, decision),
            state,
            debate_store={},
            decision_store={},
            all_queues=all_queues,
            all_replays=all_replays,
            database_url=":memory:",
            persist_queue=persist_queue,
            writer_task=writer_task,
        )

        assert thread_id not in all_queues
        assert thread_id not in all_replays
        # A fresh lock object proves the old one was released, not just reused.
        assert get_thread_lock(thread_id) is not lock_before

    @pytest.mark.anyio
    async def test_cancelled_debate_drops_replay_buffer_queue_and_lock(self):
        thread_id = str(uuid4())
        state = _make_state(thread_id, status="in_progress")

        all_queues: dict = {thread_id: []}
        all_replays: dict = {thread_id: []}
        get_thread_lock(thread_id)
        persist_queue, writer_task = _start_writer(all_queues, all_replays, thread_id)

        graph = MagicMock()
        graph.run = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await _run_debate_background(
                graph,
                state,
                debate_store={},
                decision_store={},
                all_queues=all_queues,
                all_replays=all_replays,
                database_url=":memory:",
                persist_queue=persist_queue,
                writer_task=writer_task,
            )

        assert thread_id not in all_queues
        assert thread_id not in all_replays

    @pytest.mark.anyio
    async def test_awaiting_approval_keeps_replay_buffer_and_queue(self):
        thread_id = str(uuid4())
        state = _make_state(thread_id, status="awaiting_approval")

        all_queues: dict = {thread_id: []}
        all_replays: dict = {thread_id: []}
        persist_queue, writer_task = _start_writer(all_queues, all_replays, thread_id)

        await _run_debate_background(
            _mock_graph(state, None),
            state,
            debate_store={},
            decision_store={},
            all_queues=all_queues,
            all_replays=all_replays,
            database_url=":memory:",
            persist_queue=persist_queue,
            writer_task=writer_task,
        )

        assert thread_id in all_queues
        assert thread_id in all_replays
