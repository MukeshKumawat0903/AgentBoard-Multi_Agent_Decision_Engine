"""
AgentMemoryStore.clear_memory case-insensitivity tests.

get_recent_memory/get_all_memory match agent_name with COLLATE NOCASE, so
clear_memory's DELETE must too -- otherwise DELETE /memory/<agent> can
report 0 rows deleted while GET /memory/<agent> keeps returning rows whose
stored casing differs from the request path.
"""

from __future__ import annotations

import aiosqlite
import pytest

from app.services.agent_memory import AgentMemoryStore


async def _seed_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE agent_memory (
                memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                debate_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                lesson_learned TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        await db.execute(
            "INSERT INTO agent_memory (agent_name, debate_id, summary, lesson_learned, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Analyst", "thread-1", "summary 1", "lesson 1", "2026-06-11T00:00:00+00:00"),
        )
        await db.execute(
            "INSERT INTO agent_memory (agent_name, debate_id, summary, lesson_learned, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("analyst", "thread-2", "summary 2", "lesson 2", "2026-06-11T00:00:01+00:00"),
        )
        await db.commit()


class TestClearMemoryCaseInsensitive:

    @pytest.mark.anyio
    async def test_clear_memory_removes_rows_regardless_of_stored_casing(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        await _seed_db(db_path)
        store = AgentMemoryStore(database_url=db_path, llm_client=None)

        deleted = await store.clear_memory("analyst")

        assert deleted == 2
        assert await store.get_all_memory("Analyst") == []

    @pytest.mark.anyio
    async def test_clear_memory_returns_zero_when_no_rows_match(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        await _seed_db(db_path)
        store = AgentMemoryStore(database_url=db_path, llm_client=None)

        deleted = await store.clear_memory("Strategist")

        assert deleted == 0
        assert len(await store.get_all_memory("Analyst")) == 2
