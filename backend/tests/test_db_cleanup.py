"""
Phase 6.4 — TTL cleanup and database persistence tests.

Tests cleanup_old_debates, save_evaluation/get_evaluation_json,
and debate state upsert/retrieve across restarts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from app.db.crud import (
    cleanup_old_debates,
    get_debate_state_json,
    get_evaluation_json,
    save_debate_event,
    save_evaluation,
    upsert_debate,
)
from app.schemas.state import DebateState


async def _fresh_db() -> aiosqlite.Connection:
    """Open an in-memory SQLite DB and create the minimum schema for tests."""
    db = await aiosqlite.connect(":memory:")
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS debates (
            thread_id TEXT PRIMARY KEY,
            user_query TEXT,
            status TEXT,
            current_round INTEGER,
            max_rounds INTEGER,
            agreement_score REAL,
            termination_reason TEXT,
            state_json TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS decisions (
            thread_id TEXT PRIMARY KEY,
            query TEXT,
            decision_json TEXT,
            evaluation_json TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS debate_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            event_type TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    await db.commit()
    return db


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------

class TestCleanupOldDebates:

    @pytest.mark.anyio
    async def test_old_debates_are_removed(self):
        db = await _fresh_db()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await db.execute(
            "INSERT INTO debates (thread_id, user_query, state_json, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("old-t1", "Old query", "{}", "converged", old_ts, old_ts),
        )
        await db.commit()

        deleted = await cleanup_old_debates(db, ttl_days=90)

        async with db.execute("SELECT COUNT(*) FROM debates") as cur:
            row = await cur.fetchone()
        assert row is not None
        count = row[0]
        assert count == 0
        await db.close()

    @pytest.mark.anyio
    async def test_recent_debates_are_kept(self):
        db = await _fresh_db()
        recent_ts = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO debates (thread_id, user_query, state_json, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("new-t1", "New query", "{}", "converged", recent_ts, recent_ts),
        )
        await db.commit()

        await cleanup_old_debates(db, ttl_days=90)

        async with db.execute("SELECT COUNT(*) FROM debates") as cur:
            row = await cur.fetchone()
        assert row is not None
        count = row[0]
        assert count == 1
        await db.close()

    @pytest.mark.anyio
    async def test_only_old_debates_deleted_when_mixed(self):
        db = await _fresh_db()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        new_ts = datetime.now(timezone.utc).isoformat()
        await db.executemany(
            "INSERT INTO debates (thread_id, user_query, state_json, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("old-t1", "Q1", "{}", "converged", old_ts, old_ts),
                ("new-t1", "Q2", "{}", "converged", new_ts, new_ts),
            ],
        )
        await db.commit()

        await cleanup_old_debates(db, ttl_days=90)

        async with db.execute("SELECT thread_id FROM debates") as cur:
            rows = await cur.fetchall()
        ids = {r[0] for r in rows}
        assert "new-t1" in ids
        assert "old-t1" not in ids
        await db.close()

    @pytest.mark.anyio
    async def test_cleanup_with_zero_debates_does_not_error(self):
        db = await _fresh_db()
        deleted = await cleanup_old_debates(db, ttl_days=90)
        assert deleted >= 0
        await db.close()


# ---------------------------------------------------------------------------
# Debate state persistence
# ---------------------------------------------------------------------------

class TestDebateStatePersistence:

    @pytest.mark.anyio
    async def test_upsert_and_retrieve_state(self):
        db = await _fresh_db()
        state = DebateState(user_query="Should we pivot our strategy?")
        await upsert_debate(db, state)
        await db.commit()

        retrieved_json = await get_debate_state_json(db, state.thread_id)
        assert retrieved_json is not None
        parsed = DebateState.model_validate_json(retrieved_json)
        assert parsed.thread_id == state.thread_id
        assert parsed.user_query == "Should we pivot our strategy?"
        await db.close()

    @pytest.mark.anyio
    async def test_upsert_is_idempotent(self):
        db = await _fresh_db()
        state = DebateState(user_query="Test idempotency?")
        await upsert_debate(db, state)
        state.status = "in_progress"
        state.touch()
        await upsert_debate(db, state)  # second upsert should not raise
        await db.commit()

        async with db.execute("SELECT COUNT(*) FROM debates WHERE thread_id=?", (state.thread_id,)) as cur:
            row = await cur.fetchone()
        assert row is not None
        count = row[0]
        assert count == 1
        await db.close()

    @pytest.mark.anyio
    async def test_returns_none_for_missing_thread(self):
        db = await _fresh_db()
        result = await get_debate_state_json(db, "nonexistent-thread")
        assert result is None
        await db.close()


# ---------------------------------------------------------------------------
# Evaluation persistence
# ---------------------------------------------------------------------------

class TestEvaluationPersistence:

    @pytest.mark.anyio
    async def test_save_and_retrieve_evaluation(self):
        db = await _fresh_db()
        await db.execute(
            "INSERT INTO decisions (thread_id, query, decision_json, created_at) VALUES (?, ?, ?, ?)",
            ("t-eval-1", "Q?", "{}", "2026-06-04"),
        )
        await db.commit()

        eval_json = '{"thread_id": "t-eval-1", "overall": 0.85}'
        await save_evaluation(db, "t-eval-1", eval_json)
        retrieved = await get_evaluation_json(db, "t-eval-1")

        assert retrieved == eval_json
        await db.close()

    @pytest.mark.anyio
    async def test_get_evaluation_none_when_not_saved(self):
        db = await _fresh_db()
        await db.execute(
            "INSERT INTO decisions (thread_id, query, decision_json, created_at) VALUES (?, ?, ?, ?)",
            ("t-no-eval", "Q?", "{}", "2026-06-04"),
        )
        await db.commit()
        result = await get_evaluation_json(db, "t-no-eval")
        assert result is None
        await db.close()


# ---------------------------------------------------------------------------
# Debate events persistence
# ---------------------------------------------------------------------------

class TestDebateEventsPersistence:

    @pytest.mark.anyio
    async def test_save_event_and_retrieve(self):
        from app.db.crud import get_debate_events  # noqa: PLC0415
        db = await _fresh_db()
        payload = {"type": "agent_output", "agent_name": "Analyst", "round_number": 1}
        await save_debate_event(db, "t-event-1", payload)
        await db.commit()

        events = await get_debate_events(db, "t-event-1")
        assert len(events) == 1
        assert events[0]["type"] == "agent_output"
        await db.close()

    @pytest.mark.anyio
    async def test_get_events_after_event_id(self):
        from app.db.crud import get_debate_events  # noqa: PLC0415
        db = await _fresh_db()
        payloads = [
            {"type": "round_started", "round_number": 1},
            {"type": "agent_output", "round_number": 1},
            {"type": "synthesis", "round_number": 1},
        ]
        for p in payloads:
            await save_debate_event(db, "t-events", p)
        await db.commit()

        # Retrieve all events first to get their IDs
        all_events = await get_debate_events(db, "t-events")
        assert len(all_events) == 3

        # Retrieve only events after the first one
        first_id = all_events[0]["_event_id"]
        later_events = await get_debate_events(db, "t-events", after_event_id=first_id)
        assert len(later_events) == 2
        await db.close()
