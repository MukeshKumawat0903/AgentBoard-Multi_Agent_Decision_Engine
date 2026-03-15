"""
CRUD helpers for debate history persistence.
All functions accept an open aiosqlite.Connection from the get_db() dependency.
"""

from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState

logger = logging.getLogger("agentboard.db.crud")


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def upsert_debate(db: aiosqlite.Connection, state: DebateState) -> None:
    """Insert or update the lightweight debate record."""
    await db.execute(
        """
        INSERT INTO debates
            (thread_id, user_query, status, current_round, max_rounds,
             agreement_score, termination_reason, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            status             = excluded.status,
            current_round      = excluded.current_round,
            agreement_score    = excluded.agreement_score,
            termination_reason = excluded.termination_reason,
            updated_at         = excluded.updated_at
        """,
        (
            state.thread_id,
            state.user_query,
            state.status,
            state.current_round,
            state.max_rounds,
            state.agreement_score,
            state.termination_reason,
            state.created_at.isoformat(),
            state.updated_at.isoformat(),
        ),
    )
    await db.commit()


async def save_decision(
    db: aiosqlite.Connection, decision: FinalDecision, user_query: str
) -> None:
    """Persist the full FinalDecision JSON blob, replacing any previous entry."""
    decision_text = f"{decision.decision} {decision.rationale_summary}"
    await db.execute(
        """
        INSERT OR REPLACE INTO decisions
            (thread_id, user_query, decision_text, decision_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            decision.thread_id,
            user_query,
            decision_text,
            decision.model_dump_json(),
            decision.created_at.isoformat(),
        ),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def get_history(
    db: aiosqlite.Connection,
    page: int = 1,
    limit: int = 20,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return a page of completed debates, optionally filtered by free-text search.

    Returns (items, total_count).
    """
    offset = (page - 1) * limit

    base_join = """
        FROM    decisions dec
        LEFT JOIN debates deb ON deb.thread_id = dec.thread_id
    """
    select_cols = """
        SELECT  dec.thread_id,
                dec.user_query,
                dec.created_at,
                deb.status,
                deb.current_round,
                deb.max_rounds,
                deb.agreement_score,
                deb.termination_reason
    """

    if q:
        pattern = f"%{q}%"
        where = "WHERE dec.user_query LIKE ? OR dec.decision_text LIKE ?"
        count_args: tuple = (pattern, pattern)
        list_args: tuple = (pattern, pattern, limit, offset)
    else:
        where = ""
        count_args = ()
        list_args = (limit, offset)

    cur = await db.execute(
        f"SELECT COUNT(*) {base_join} {where}", count_args
    )
    row = await cur.fetchone()
    total: int = row[0] if row else 0

    cur = await db.execute(
        f"{select_cols} {base_join} {where} ORDER BY dec.created_at DESC LIMIT ? OFFSET ?",
        list_args,
    )
    rows = await cur.fetchall()

    items: list[dict[str, Any]] = [
        {
            "thread_id":          r[0],
            "user_query":         r[1],
            "created_at":         r[2],
            "status":             r[3] or "converged",
            "total_rounds":       r[5] or 4,
            "agreement_score":    float(r[6]) if r[6] is not None else 0.0,
            "termination_reason": r[7] or "consensus_reached",
        }
        for r in rows
    ]
    return items, total


async def get_decision_json(
    db: aiosqlite.Connection, thread_id: str
) -> str | None:
    """Return the raw JSON string of a stored FinalDecision, or None if not found."""
    cur = await db.execute(
        "SELECT decision_json FROM decisions WHERE thread_id = ?", (thread_id,)
    )
    row = await cur.fetchone()
    return row[0] if row else None
