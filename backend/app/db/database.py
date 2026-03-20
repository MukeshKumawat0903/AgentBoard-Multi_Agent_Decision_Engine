"""
Async SQLite database setup for AgentBoard persistence.

Tables are created on startup via init_db(); each request uses get_db().
Schema includes:
- debates       : lightweight status row + full DebateState JSON snapshot
- decisions     : full FinalDecision JSON blob
- debate_events : ordered replayable SSE event history per thread
"""

import logging

import aiosqlite

from app.core.config import settings

logger = logging.getLogger("agentboard.db")


async def _ensure_column(
    db: aiosqlite.Connection,
    table_name: str,
    column_name: str,
    ddl: str,
) -> None:
    """Add a column if the existing table was created before the new schema."""
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    rows = await cursor.fetchall()
    existing = {row[1] for row in rows}
    if column_name not in existing:
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


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
                state_json         TEXT,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            )
            """
        )
        await _ensure_column(db, "debates", "state_json", "state_json TEXT")
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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS debate_events (
                event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id    TEXT NOT NULL,
                event_type   TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_debate_events_thread_event_id "
            "ON debate_events(thread_id, event_id)"
        )
        await db.commit()
    logger.info("Database initialized")


async def get_db():
    """FastAPI dependency – yields a configured aiosqlite connection."""
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        yield db
