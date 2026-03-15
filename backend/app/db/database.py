"""
Async SQLite database setup for AgentBoard history persistence.
Tables are created on startup via init_db(); each request uses get_db().
"""

import logging

import aiosqlite

from app.core.config import settings

logger = logging.getLogger("agentboard.db")


async def init_db() -> None:
    """Create all tables and indexes if they don't already exist."""
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS debates (
                thread_id          TEXT PRIMARY KEY,
                user_query         TEXT NOT NULL,
                status             TEXT NOT NULL,
                current_round      INTEGER DEFAULT 0,
                max_rounds         INTEGER DEFAULT 4,
                agreement_score    REAL    DEFAULT 0.0,
                termination_reason TEXT,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                thread_id     TEXT PRIMARY KEY,
                user_query    TEXT NOT NULL,
                decision_text TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_created "
            "ON decisions(created_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_debates_created "
            "ON debates(created_at DESC)"
        )
        await db.commit()
    logger.info("Database initialized")


async def get_db():
    """FastAPI dependency – yields a configured aiosqlite connection."""
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        yield db
