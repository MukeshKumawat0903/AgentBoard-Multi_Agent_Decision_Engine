"""
CRUD helpers for debate persistence.

All functions accept an open aiosqlite.Connection from the get_db() dependency.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
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
             agreement_score, termination_reason, state_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            status             = excluded.status,
            current_round      = excluded.current_round,
            agreement_score    = excluded.agreement_score,
            termination_reason = excluded.termination_reason,
            state_json         = excluded.state_json,
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
            state.model_dump_json(),
            state.created_at.isoformat(),
            state.updated_at.isoformat(),
        ),
    )
    await db.commit()


async def save_decision(
    db: aiosqlite.Connection, decision: FinalDecision, user_query: str
) -> None:
    """Persist the full FinalDecision JSON blob.

    Uses an upsert that preserves any cached ``evaluation_json`` for this
    thread_id — a plain ``INSERT OR REPLACE`` would delete-then-reinsert the
    row and silently wipe a previously cached evaluation (e.g. when a HITL
    approve flow re-saves a decision after it was evaluated).
    """
    decision_text = f"{decision.decision} {decision.rationale_summary}"
    await db.execute(
        """
        INSERT INTO decisions
            (thread_id, user_query, decision_text, decision_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            user_query    = excluded.user_query,
            decision_text = excluded.decision_text,
            decision_json = excluded.decision_json,
            created_at    = excluded.created_at
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
                deb.termination_reason,
                deb.state_json
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

    def _parse_flags(state_json_str: str | None) -> tuple[bool, bool]:
        """Extract use_knowledge_base and enable_agent_memory from state JSON."""
        if not state_json_str:
            return False, False
        try:
            import json as _json
            s = _json.loads(state_json_str)
            return bool(s.get("use_knowledge_base")), bool(s.get("enable_agent_memory"))
        except Exception:  # noqa: BLE001
            return False, False

    items: list[dict[str, Any]] = []
    for r in rows:
        use_kb, use_mem = _parse_flags(r[8])
        items.append({
            "thread_id":            r[0],
            "user_query":           r[1],
            "created_at":           r[2],
            "status":               r[3] or "converged",
            "total_rounds":         r[5] or 4,
            "agreement_score":      float(r[6]) if r[6] is not None else 0.0,
            "termination_reason":   r[7] or "consensus_reached",
            "use_knowledge_base":   use_kb,
            "enable_agent_memory":  use_mem,
        })
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


async def get_debate_state_json(
    db: aiosqlite.Connection,
    thread_id: str,
) -> str | None:
    """Return the full DebateState JSON snapshot, or None if not found."""
    cur = await db.execute(
        "SELECT state_json FROM debates WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def save_debate_event(
    db: aiosqlite.Connection,
    thread_id: str,
    payload: dict[str, Any],
) -> int:
    """Persist a single replayable SSE payload for later recovery.  Returns the new event_id."""
    cur = await db.execute(
        """
        INSERT INTO debate_events (thread_id, event_type, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            thread_id,
            payload.get("type", "message"),
            json.dumps(payload),
            datetime.now(UTC).isoformat(),
        ),
    )
    await db.commit()
    return cur.lastrowid or 0


async def get_debate_events(
    db: aiosqlite.Connection,
    thread_id: str,
    after_event_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return ordered replayable SSE payloads for a debate.

    When ``after_event_id`` is given, only events with ``event_id > after_event_id``
    are returned, supporting efficient SSE reconnection replay.
    """
    if after_event_id is not None:
        cur = await db.execute(
            "SELECT event_id, payload_json FROM debate_events "
            "WHERE thread_id = ? AND event_id > ? ORDER BY event_id ASC",
            (thread_id, after_event_id),
        )
    else:
        cur = await db.execute(
            "SELECT event_id, payload_json FROM debate_events "
            "WHERE thread_id = ? ORDER BY event_id ASC",
            (thread_id,),
        )
    rows = await cur.fetchall()
    result = []
    for row in rows:
        payload = json.loads(row[1])
        payload["_event_id"] = row[0]  # attach db event_id for SSE id field
        result.append(payload)
    return result


# ---------------------------------------------------------------------------
# Lifecycle / TTL cleanup
# ---------------------------------------------------------------------------


async def cleanup_old_debates(
    db: aiosqlite.Connection,
    ttl_days: int = 90,
) -> None:
    """Delete debates, decisions, and events older than ``ttl_days`` days.

    Runs once at application startup.  Safe to call on an empty database.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()

    cur = await db.execute(
        "DELETE FROM debate_events WHERE created_at < ?", (cutoff,)
    )
    events_deleted = cur.rowcount

    cur = await db.execute(
        "DELETE FROM decisions WHERE created_at < ?", (cutoff,)
    )
    decisions_deleted = cur.rowcount

    cur = await db.execute(
        "DELETE FROM debates WHERE created_at < ?", (cutoff,)
    )
    debates_deleted = cur.rowcount

    await db.commit()

    logger.info(
        "cleanup_complete",
        extra={
            "ttl_days": ttl_days,
            "debates_deleted": debates_deleted,
            "decisions_deleted": decisions_deleted,
            "events_deleted": events_deleted,
        },
    )


# ---------------------------------------------------------------------------
# P4.3 – Evaluation caching
# ---------------------------------------------------------------------------


async def get_evaluation_json(
    db: aiosqlite.Connection, thread_id: str
) -> str | None:
    """Return the cached evaluation JSON for a decision, or None if not yet evaluated."""
    cur = await db.execute(
        "SELECT evaluation_json FROM decisions WHERE thread_id = ?", (thread_id,)
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def save_evaluation(
    db: aiosqlite.Connection, thread_id: str, eval_json: str
) -> None:
    """Persist the evaluation JSON blob for an existing decision row."""
    await db.execute(
        "UPDATE decisions SET evaluation_json = ? WHERE thread_id = ?",
        (eval_json, thread_id),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Phase 5 — Analytics & Evaluation queries
# All queries target the existing debates / decisions / debate_events tables.
# ---------------------------------------------------------------------------


def _date_clause(days: int) -> str:
    """Return an ``AND created_at >= ...`` SQL fragment, or empty for all-time.

    ``days`` is an int the caller controls (never raw user text), so interpolating
    it into the DATE modifier is safe here.
    """
    return f"AND created_at >= DATE('now', '-{int(days)} days')" if days and days > 0 else ""


async def get_analytics_overview(db: aiosqlite.Connection, days: int = 0) -> dict[str, Any]:
    """Aggregate overview stats for completed debates, optionally scoped to N days."""
    dc = _date_clause(days)
    cur = await db.execute(
        f"SELECT COUNT(*) FROM debates WHERE status IN ('converged', 'max_rounds_reached') {dc}"
    )
    row = await cur.fetchone()
    total_debates: int = row[0] if row else 0

    cur = await db.execute(
        f"""
        SELECT AVG(current_round), AVG(agreement_score)
        FROM debates
        WHERE status IN ('converged', 'max_rounds_reached') {dc}
        """
    )
    row = await cur.fetchone()
    avg_rounds = float(row[0]) if row and row[0] is not None else 0.0
    avg_agreement = float(row[1]) if row and row[1] is not None else 0.0

    cur = await db.execute(
        f"""
        SELECT COALESCE(termination_reason, 'unknown'), COUNT(*)
        FROM debates
        WHERE status IN ('converged', 'max_rounds_reached') {dc}
        GROUP BY termination_reason
        """
    )
    rows = await cur.fetchall()
    debates_by_termination: dict[str, int] = {r[0]: r[1] for r in rows}

    trend_days = days if days and days > 0 else 30
    cur = await db.execute(
        f"""
        SELECT DATE(created_at) AS day, COUNT(*) AS cnt
        FROM debates
        WHERE created_at >= DATE('now', '-{int(trend_days)} days')
        GROUP BY day
        ORDER BY day ASC
        """
    )
    rows = await cur.fetchall()
    debates_per_day = [{"date": r[0], "count": r[1]} for r in rows]

    return {
        "total_debates": total_debates,
        "avg_rounds_to_consensus": round(avg_rounds, 2),
        "avg_agreement_score": round(avg_agreement, 3),
        "debates_by_termination": debates_by_termination,
        "debates_per_day": debates_per_day,
    }


async def get_analytics_agents(db: aiosqlite.Connection, days: int = 0) -> dict[str, Any]:
    """Per-agent performance stats derived from stored state and decision JSON blobs."""
    dc = _date_clause(days)
    cur = await db.execute(
        f"""
        SELECT state_json FROM debates
        WHERE status IN ('converged', 'max_rounds_reached') AND state_json IS NOT NULL {dc}
        """
    )
    state_rows = await cur.fetchall()

    cur = await db.execute(
        f"SELECT decision_json FROM decisions WHERE decision_json IS NOT NULL {dc}"
    )
    decision_rows = await cur.fetchall()

    confidence_sums: dict[str, list[float]] = {}
    critique_severity_counts: dict[str, dict[str, int]] = {}
    contribution_sums: dict[str, list[float]] = {}
    high_conf_per_debate: list[set[str]] = []

    for row in state_rows:
        try:
            state = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            continue

        final_conf: dict[str, float] = state.get("confidence_scores", {})
        for agent, score in final_conf.items():
            confidence_sums.setdefault(agent, []).append(float(score))

        high_conf = {a for a, s in final_conf.items() if float(s) > 0.7}
        if high_conf:
            high_conf_per_debate.append(high_conf)

        for round_data in state.get("rounds", []):
            for critique in round_data.get("critiques", []):
                critic = critique.get("critic_agent", "")
                severity = critique.get("severity", "low")
                if critic:
                    sev = critique_severity_counts.setdefault(critic, {})
                    sev[severity] = sev.get(severity, 0) + 1

    for drow in decision_rows:
        try:
            decision = json.loads(drow[0])
        except (json.JSONDecodeError, TypeError):
            continue
        for agent, score in (decision.get("agent_contribution_scores") or {}).items():
            contribution_sums.setdefault(agent, []).append(float(score))

    all_agents = sorted(set(confidence_sums) | set(critique_severity_counts) | set(contribution_sums))
    agent_stats: dict[str, dict] = {}
    for agent in all_agents:
        confs = confidence_sums.get(agent, [])
        contribs = contribution_sums.get(agent, [])
        agent_stats[agent] = {
            "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
            "avg_critique_severity_given": critique_severity_counts.get(agent, {}),
            "avg_contribution_score": round(sum(contribs) / len(contribs), 3) if contribs else 0.0,
        }

    # Pairwise agreement matrix: fraction where both agents had confidence > 0.7
    matrix: dict[str, dict[str, float]] = {}
    for a in all_agents:
        matrix[a] = {}
        a_debates = sum(1 for hc in high_conf_per_debate if a in hc)
        for b in all_agents:
            if a == b:
                matrix[a][b] = 1.0
                continue
            both = sum(1 for hc in high_conf_per_debate if a in hc and b in hc)
            matrix[a][b] = round(both / a_debates, 3) if a_debates > 0 else 0.0

    return {"agents": agent_stats, "agreement_matrix": matrix}


async def get_analytics_convergence(db: aiosqlite.Connection, days: int = 0) -> dict[str, Any]:
    """Convergence curve, mode breakdown, and domain pack breakdown."""
    dc = _date_clause(days)
    cur = await db.execute(
        f"SELECT payload_json FROM debate_events WHERE event_type = 'synthesis' {dc}"
    )
    rows = await cur.fetchall()
    round_scores: dict[int, list[float]] = {}
    for row in rows:
        try:
            payload = json.loads(row[0])
            rn = int(payload.get("round_number", 0))
            score = float(payload.get("agreement_score", 0.0))
            if rn > 0:
                round_scores.setdefault(rn, []).append(score)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    max_round = max(round_scores.keys(), default=0)
    avg_agreement_by_round = [
        round(sum(round_scores[r]) / len(round_scores[r]), 3)
        for r in range(1, max_round + 1)
        if round_scores.get(r)
    ]

    cur = await db.execute(
        f"""
        SELECT max_rounds, COUNT(*) AS cnt
        FROM debates
        WHERE status IN ('converged', 'max_rounds_reached') {dc}
        GROUP BY max_rounds
        """
    )
    rows = await cur.fetchall()
    _mode_map = {2: "quick", 4: "standard", 6: "thorough"}
    mode_breakdown: dict[str, int] = {}
    for row in rows:
        label = _mode_map.get(row[0], f"custom_{row[0]}")
        mode_breakdown[label] = mode_breakdown.get(label, 0) + row[1]

    cur = await db.execute(
        f"""
        SELECT state_json FROM debates
        WHERE status IN ('converged', 'max_rounds_reached') AND state_json IS NOT NULL {dc}
        """
    )
    rows = await cur.fetchall()
    domain_pack_counts: dict[str, int] = {}
    for row in rows:
        try:
            state = json.loads(row[0])
            pack = state.get("domain_pack") or "default"
            domain_pack_counts[pack] = domain_pack_counts.get(pack, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "avg_agreement_by_round": avg_agreement_by_round,
        "mode_breakdown": mode_breakdown,
        "domain_pack_breakdown": domain_pack_counts,
    }


async def get_analytics_quality(db: aiosqlite.Connection, days: int = 0) -> dict[str, Any]:
    """Quality score analytics from stored evaluation JSON blobs."""
    qdc = (
        f"AND dec.created_at >= DATE('now', '-{int(days)} days')"
        if days and days > 0
        else ""
    )
    cur = await db.execute(
        f"""
        SELECT deb.state_json, dec.evaluation_json
        FROM decisions dec
        JOIN debates deb ON deb.thread_id = dec.thread_id
        WHERE dec.evaluation_json IS NOT NULL {qdc}
        """
    )
    rows = await cur.fetchall()

    if not rows:
        return {
            "evaluated_count": 0,
            "avg_quality_score": None,
            "scores_by_template": {},
            "scores_by_mode": {},
            "scores_by_domain_pack": {},
            "best_performing_templates": [],
            "worst_performing_templates": [],
        }

    _mode_map = {2: "quick", 4: "standard", 6: "thorough"}
    template_scores: dict[str, list[float]] = {}
    mode_scores: dict[str, list[float]] = {}
    domain_scores: dict[str, list[float]] = {}
    all_scores: list[float] = []

    for state_json_str, eval_json_str in rows:
        try:
            eval_data = json.loads(eval_json_str)
            # EvaluationResult serialises its score as "overall"; "quality_score"/
            # "overall_score" are kept as fallbacks for any legacy cached rows.
            quality = float(
                eval_data.get(
                    "overall",
                    eval_data.get("quality_score", eval_data.get("overall_score", 0.0)),
                )
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        all_scores.append(quality)

        try:
            state = json.loads(state_json_str) if state_json_str else {}
        except (json.JSONDecodeError, TypeError):
            state = {}

        template = state.get("template_id") or state.get("domain_pack") or "default"
        template_scores.setdefault(template, []).append(quality)

        mode = _mode_map.get(state.get("max_rounds", 4), "custom")
        mode_scores.setdefault(mode, []).append(quality)

        dp = state.get("domain_pack") or "default"
        domain_scores.setdefault(dp, []).append(quality)

    avg_by_template = {t: round(sum(v) / len(v), 3) for t, v in template_scores.items()}
    sorted_tmpl = sorted(avg_by_template.items(), key=lambda x: x[1])
    worst = [t for t, _ in sorted_tmpl[:3]]
    best = [t for t, _ in reversed(sorted_tmpl[-3:])]

    return {
        "evaluated_count": len(all_scores),
        "avg_quality_score": round(sum(all_scores) / len(all_scores), 3) if all_scores else None,
        "scores_by_template": avg_by_template,
        "scores_by_mode": {m: round(sum(v) / len(v), 3) for m, v in mode_scores.items()},
        "scores_by_domain_pack": {d: round(sum(v) / len(v), 3) for d, v in domain_scores.items()},
        "best_performing_templates": best,
        "worst_performing_templates": worst,
    }
