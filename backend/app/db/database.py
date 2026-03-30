"""
Async SQLite database setup for AgentBoard persistence.

Schema is managed via Alembic migrations (backend/alembic/).
Tables:
- debates       : lightweight status row + full DebateState JSON snapshot
- decisions     : full FinalDecision JSON blob
- debate_events : ordered replayable SSE event history per thread

To apply migrations on startup, call ``run_migrations()`` from the
``lifespan`` context manager in ``main.py``.
To generate a new migration after a schema change::

    cd backend/
    alembic revision --autogenerate -m "describe_your_change"

"""

import logging
import os
import sqlite3
import sys
from importlib import import_module
from typing import Any

import aiosqlite

from app.core.config import settings

logger = logging.getLogger("agentboard.db")

_INITIAL_SCHEMA_REVISION = "fd8050f88af3"
_PHASE3_PHASE4_REVISION = "a1b2c3d4e5f6"


def _import_alembic_runtime() -> tuple[Any, Any]:
    """Import installed Alembic modules without being shadowed by backend/alembic/."""
    backend_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    original_sys_path = list(sys.path)
    normalized_backend_root = os.path.normcase(os.path.normpath(backend_root))

    try:
        sys.path = [
            path
            for path in sys.path
            if os.path.normcase(os.path.normpath(os.path.abspath(path or os.curdir)))
            != normalized_backend_root
        ]
        config_module = import_module("alembic.config")
        command_module = import_module("alembic.command")
        return config_module.Config, command_module
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Alembic is required at runtime. Install backend requirements into the active venv."
        ) from exc
    finally:
        sys.path = original_sys_path


def _resolve_sqlite_db_path(database_url: str) -> str | None:
    """Resolve the configured SQLite database path, if applicable."""
    if database_url == ":memory:":
        return None
    if database_url.startswith("sqlite:///"):
        return database_url.removeprefix("sqlite:///")
    if "://" in database_url:
        return None
    return os.path.abspath(database_url)


def _prepare_legacy_sqlite_migration_state(database_url: str) -> str | None:
    """Return a revision to stamp for a legacy SQLite DB, or None for fresh DBs.

    Cases handled:
    - Fresh DB: no tables yet -> return None.
    - Legacy pre-Alembic DB with complete schema -> return revision to stamp.
    - Partial empty DB from failed initial migration -> drop partial tables and return None.
    """
    db_path = _resolve_sqlite_db_path(database_url)
    if db_path is None or not os.path.exists(db_path):
        return None

    core_tables = {"debates", "decisions", "debate_events"}

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        tables = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "alembic_version" in tables:
            version_rows = cursor.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchall()
            if version_rows:
                return None

        existing_core_tables = tables & core_tables
        if not existing_core_tables:
            return None

        if existing_core_tables != core_tables:
            counts = {
                table: cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in existing_core_tables
            }
            if all(count == 0 for count in counts.values()):
                for table in existing_core_tables:
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
                logger.warning(
                    "partial_legacy_schema_reset",
                    extra={"tables_removed": sorted(existing_core_tables)},
                )
                return None
            raise RuntimeError(
                "Database is in a partial pre-Alembic state. Back up the DB and remove the incomplete core tables before restarting."
            )

        decision_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(decisions)").fetchall()
        }
        if "agent_memory" in tables and "evaluation_json" in decision_columns:
            return _PHASE3_PHASE4_REVISION
        return _INITIAL_SCHEMA_REVISION


def run_migrations() -> None:
    """
    Apply all pending Alembic migrations synchronously.

    Called once at application startup from the lifespan context manager.
    Uses `alembic upgrade head` semantics: safe to run on an already
    up-to-date database (no-op if nothing to migrate).
    """
    Config, command = _import_alembic_runtime()
    backend_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    alembic_cfg = Config(
        os.path.join(backend_root, "alembic.ini")
    )
    # Override the script location so it resolves relative to this file
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(backend_root, "alembic"),
    )

    legacy_revision = _prepare_legacy_sqlite_migration_state(settings.DATABASE_URL)
    if legacy_revision is not None:
        command.stamp(alembic_cfg, legacy_revision)
        logger.info(
            "legacy_database_stamped",
            extra={"revision": legacy_revision},
        )

    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied")


async def get_db():
    """FastAPI dependency – yields a configured aiosqlite connection."""
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        yield db

