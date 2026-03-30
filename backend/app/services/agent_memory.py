"""
Agent Memory Store for AgentBoard.

After each debate completes, each agent's final position is summarised
by an LLM call into one lesson sentence and stored in the ``agent_memory``
table.  At the start of subsequent debates (when ``enable_agent_memory=True``),
recent lessons are injected into each agent's system prompt.

Usage::

    from app.services.agent_memory import AgentMemoryStore

    memory = AgentMemoryStore(llm_client=client)

    # Save a memory after debate completes
    await memory.save_memory("Analyst", "thread-123", "Final position text...")

    # Retrieve for prompt injection
    lessons = await memory.get_recent_memory("Analyst", limit=5)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiosqlite
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.services.llm_client import LangChainProvider

logger = logging.getLogger("agentboard.memory")


# ---------------------------------------------------------------------------
# Value schema
# ---------------------------------------------------------------------------

class _MemorySummaryOutput(BaseModel):
    summary: str = Field(description="One-sentence summary of the agent's final position.")
    lesson: str = Field(description="One-sentence lesson learned that could improve future debates.")


# ---------------------------------------------------------------------------
# AgentMemoryStore
# ---------------------------------------------------------------------------

class AgentMemoryStore:
    """
    Stores and retrieves per-agent debate memories in SQLite.

    The ``agent_memory`` table must already exist (created by Alembic migration).
    """

    def __init__(self, database_url: str, llm_client: LangChainProvider) -> None:
        self._db_url = database_url
        self._llm_client = llm_client

    async def save_memory(
        self,
        agent_name: str,
        debate_id: str,
        position_text: str,
    ) -> None:
        """
        Summarise the agent's final position and persist it.

        Uses the LLM to extract a one-sentence summary and lesson.
        Failures are logged as warnings and do not propagate.
        """
        try:
            summary_obj = await self._llm_client.ainvoke_structured(
                _MemorySummaryOutput,
                system_prompt=(
                    "You are a concise summariser.  Given a debate agent's final position text, "
                    "extract exactly two things: "
                    "1) A one-sentence summary of the agent's final stance. "
                    "2) One transferable lesson the agent should remember for future debates. "
                    "Be specific and actionable."
                ),
                user_prompt=f"Agent: {agent_name}\nFinal position:\n{position_text[:2000]}",
            )
            async with aiosqlite.connect(self._db_url) as db:
                await db.execute(
                    """
                    INSERT INTO agent_memory
                        (agent_name, debate_id, summary, lesson_learned, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        agent_name,
                        debate_id,
                        summary_obj.summary,
                        summary_obj.lesson,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                await db.commit()
            logger.info(
                "memory_saved",
                extra={"agent": agent_name, "debate_id": debate_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory_save_failed",
                extra={"agent": agent_name, "debate_id": debate_id, "error": str(exc)},
            )

    async def get_recent_memory(
        self,
        agent_name: str,
        limit: int = 5,
    ) -> list[str]:
        """Return the most recent ``limit`` lesson_learned strings for this agent."""
        try:
            async with aiosqlite.connect(self._db_url) as db:
                cur = await db.execute(
                    """
                    SELECT lesson_learned
                    FROM agent_memory
                    WHERE agent_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (agent_name, limit),
                )
                rows = await cur.fetchall()
                return [row[0] for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory_fetch_failed",
                extra={"agent": agent_name, "error": str(exc)},
            )
            return []

    async def get_all_memory(
        self,
        agent_name: str,
        limit: int = 20,
    ) -> list[dict]:
        """Return full memory rows for an agent (used by API endpoints)."""
        try:
            async with aiosqlite.connect(self._db_url) as db:
                cur = await db.execute(
                    """
                    SELECT memory_id, agent_name, debate_id, summary, lesson_learned, created_at
                    FROM agent_memory
                    WHERE agent_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (agent_name, limit),
                )
                rows = await cur.fetchall()
                return [
                    {
                        "memory_id": r[0],
                        "agent_name": r[1],
                        "debate_id": r[2],
                        "summary": r[3],
                        "lesson_learned": r[4],
                        "created_at": r[5],
                    }
                    for r in rows
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_list_failed", extra={"agent": agent_name, "error": str(exc)})
            return []

    async def clear_memory(self, agent_name: str) -> int:
        """Delete all memory entries for an agent.  Returns deleted count."""
        try:
            async with aiosqlite.connect(self._db_url) as db:
                cur = await db.execute(
                    "DELETE FROM agent_memory WHERE agent_name = ?", (agent_name,)
                )
                await db.commit()
                deleted = cur.rowcount
                logger.info(
                    "memory_cleared",
                    extra={"agent": agent_name, "deleted": deleted},
                )
                return deleted
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_clear_failed", extra={"agent": agent_name, "error": str(exc)})
            return 0
