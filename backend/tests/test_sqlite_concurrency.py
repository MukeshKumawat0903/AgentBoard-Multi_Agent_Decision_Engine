"""
Concurrent debates write events and state snapshots while other requests read.
The database runs in WAL mode, and a transient "database is locked" no longer
drops an event from the reconnect-replay history.
"""

import asyncio
import sqlite3
from unittest.mock import patch

import aiosqlite
import pytest

from app.api.routes import _event_writer_loop
from app.core.config import settings
from app.db.crud import get_debate_events, save_debate_event


def test_migrated_database_uses_wal():
    with sqlite3.connect(settings.DATABASE_URL) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


async def _run_writer(payloads: list[dict]) -> list[dict]:
    persist: asyncio.Queue = asyncio.Queue()
    subscriber: asyncio.Queue = asyncio.Queue()
    writer = asyncio.create_task(
        _event_writer_loop(persist, [subscriber], [], "t-lock", settings.DATABASE_URL)
    )
    for p in payloads:
        persist.put_nowait(p)
    persist.put_nowait(None)
    await asyncio.wait_for(writer, 10)
    return [subscriber.get_nowait() for _ in payloads]


@pytest.mark.anyio
async def test_transient_lock_is_retried_without_duplicates():
    calls = {"n": 0}

    async def flaky_save(db, thread_id, payload):
        calls["n"] += 1
        if calls["n"] <= 2:
            # Simulate "insert ran, commit hit the lock": the row must be rolled back.
            await db.execute(
                "INSERT INTO debate_events (thread_id, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)", (thread_id, "partial", "{}", "now"),
            )
            raise sqlite3.OperationalError("database is locked")
        return await save_debate_event(db, thread_id, payload)

    with patch("app.api.routes.save_debate_event", side_effect=flaky_save):
        broadcast = await _run_writer([{"type": "round_started", "round_number": 1}])

    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        stored = await get_debate_events(db, "t-lock")
    assert [e["type"] for e in stored] == ["round_started"]  # no "partial" leftovers
    assert broadcast[0]["_event_id"] == stored[0]["_event_id"]


@pytest.mark.anyio
async def test_persistent_lock_gives_up_but_still_broadcasts():
    async def always_locked(db, thread_id, payload):
        raise sqlite3.OperationalError("database is locked")

    with patch("app.api.routes.save_debate_event", side_effect=always_locked), \
         patch("app.api.routes.asyncio.sleep") as no_wait:
        no_wait.return_value = None
        broadcast = await _run_writer([{"type": "synthesis", "round_number": 1}])

    assert broadcast[0]["type"] == "synthesis"  # live subscribers still get it
    assert "_event_id" not in broadcast[0]
