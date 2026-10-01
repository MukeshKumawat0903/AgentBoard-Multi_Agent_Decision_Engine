"""
Small storage guarantees: re-saving a decision keeps its place in history, and
agent-memory lookups (case-insensitive by name) are served by an index.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from app.core.config import settings
from app.db.crud import get_decision_json, get_history, save_decision
from app.schemas.final_decision import FinalDecision
from app.services.agent_memory import AgentMemoryStore

_T0 = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _decision(thread_id: str, created_at: datetime, decision: str = "Proceed") -> FinalDecision:
    return FinalDecision(
        thread_id=thread_id,
        decision=decision,
        rationale_summary="why",
        confidence_score=0.8,
        agreement_score=0.7,
        total_rounds=1,
        termination_reason="consensus_reached",
        created_at=created_at,
    )


@pytest.mark.anyio
async def test_resaving_a_decision_keeps_its_original_timestamp():
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await save_decision(db, _decision("first", _T0), "First question")
        await save_decision(db, _decision("second", _T0 + timedelta(hours=1)), "Second question")
        await save_decision(db, _decision("first", _T0 + timedelta(days=1), "Revised"), "First question")
        items, _ = await get_history(db)
        stored = await get_decision_json(db, "first")

    assert [i["thread_id"] for i in items] == ["second", "first"]
    assert items[1]["created_at"].startswith("2026-03-01T00:00:00")
    assert '"decision":"Revised"' in stored


def _plan(sql: str) -> str:
    with sqlite3.connect(settings.DATABASE_URL) as conn:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, ("strategist", 5)[: sql.count("?")]).fetchall()
    return " | ".join(row[-1] for row in rows)


def test_memory_lookups_use_the_case_insensitive_index():
    recent = _plan(
        "SELECT lesson_learned FROM agent_memory WHERE agent_name = ? COLLATE NOCASE "
        "ORDER BY created_at DESC LIMIT ?"
    )
    clear = _plan("DELETE FROM agent_memory WHERE agent_name = ? COLLATE NOCASE")

    assert "idx_agent_memory_agent_nocase_created" in recent
    assert "TEMP B-TREE" not in recent
    assert "idx_agent_memory_agent_nocase_created" in clear


@pytest.mark.anyio
async def test_memory_lookup_is_still_case_insensitive():
    store = AgentMemoryStore(llm_client=object(), database_url=settings.DATABASE_URL)
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        for i, name in enumerate(["Strategist", "strategist", "Critic"]):
            await db.execute(
                "INSERT INTO agent_memory (agent_name, debate_id, summary, lesson_learned, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, f"d{i}", "s", f"lesson {i}", (_T0 + timedelta(minutes=i)).isoformat()),
            )
        await db.commit()

    assert await store.get_recent_memory("STRATEGIST") == ["lesson 1", "lesson 0"]
    assert await store.clear_memory("strategist") == 2
    assert await store.get_recent_memory("critic") == ["lesson 2"]
