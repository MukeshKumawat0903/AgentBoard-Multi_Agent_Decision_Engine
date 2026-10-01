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

from app.core.config import settings
from app.data.templates import TEMPLATES
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.consensus import _word_overlap, normalize_position_overlap

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
    approve flow re-saves a decision after it was evaluated). The original
    ``created_at`` is kept too, so a re-save doesn't move the debate in history.
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
            decision_json = excluded.decision_json
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


# Whitelisted ORDER BY clauses for the history list.
HISTORY_SORTS: dict[str, str] = {
    "newest": "dec.created_at DESC",
    "oldest": "dec.created_at ASC",
    "highest_agreement": (
        "COALESCE(deb.agreement_score, json_extract(dec.decision_json, '$.agreement_score'), 0) DESC, "
        "dec.created_at DESC"
    ),
}


def _escape_like(text: str) -> str:
    """Make ``%`` and ``_`` in user search text match literally (used with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_history(
    db: aiosqlite.Connection,
    page: int = 1,
    limit: int = 20,
    q: str | None = None,
    sort: str = "newest",
    termination_reason: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return a page of completed debates, optionally searched, filtered and sorted.

    Filtering and sorting happen in SQL so they apply to the whole history,
    not just the page being shown. Returns (items, total_count).
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
                deb.state_json,
                json_extract(dec.decision_json, '$.total_rounds'),
                json_extract(dec.decision_json, '$.termination_reason'),
                json_extract(dec.decision_json, '$.agreement_score')
    """

    conditions: list[str] = []
    args: list[Any] = []
    if q:
        pattern = f"%{_escape_like(q)}%"
        conditions.append(
            "(dec.user_query LIKE ? ESCAPE '\\' OR dec.decision_text LIKE ? ESCAPE '\\')"
        )
        args += [pattern, pattern]
    if termination_reason:
        conditions.append(
            "COALESCE(deb.termination_reason, json_extract(dec.decision_json, '$.termination_reason')) = ?"
        )
        args.append(termination_reason)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_by = HISTORY_SORTS.get(sort, HISTORY_SORTS["newest"])

    cur = await db.execute(f"SELECT COUNT(*) {base_join} {where}", tuple(args))
    row = await cur.fetchone()
    total: int = row[0] if row else 0

    cur = await db.execute(
        f"{select_cols} {base_join} {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
        (*args, limit, offset),
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
        # The debates row can be missing (e.g. removed separately); fall back to
        # what the stored decision itself recorded rather than inventing values.
        termination_reason = r[7] or r[10] or "unknown"
        rounds_run = r[4] or r[9] or 0
        agreement = r[6] if r[6] is not None else r[11]
        items.append({
            "thread_id":            r[0],
            "user_query":           r[1],
            "created_at":           r[2],
            "status":               r[3] or _status_for_reason(termination_reason),
            "total_rounds":         int(rounds_run),
            "agreement_score":      float(agreement) if agreement is not None else 0.0,
            "termination_reason":   termination_reason,
            "use_knowledge_base":   use_kb,
            "enable_agent_memory":  use_mem,
        })
    return items, total


def _status_for_reason(termination_reason: str) -> str:
    """Terminal status implied by a termination reason (mirrors finalize_node)."""
    if termination_reason in ("consensus_reached", "human_override"):
        return "converged"
    return "max_rounds_reached"


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
) -> int:
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

    return debates_deleted


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


def _date_clause(days: int, column: str = "created_at") -> str:
    """Return an ``AND <column> >= ...`` SQL fragment, or empty for all-time.

    ``days`` is an int the caller controls (never raw user text), so interpolating
    it into the DATE modifier is safe here.
    """
    return f"AND {column} >= DATE('now', '-{int(days)} days')" if days and days > 0 else ""


# Debates that ran to a decision. Older debates rows have no termination_reason,
# so it falls back to the stored decision (as the history list does).
_COMPLETED_DEBATES = (
    "FROM debates deb LEFT JOIN decisions dec ON dec.thread_id = deb.thread_id "
    "WHERE deb.status IN ('converged', 'max_rounds_reached')"
)
_TERMINATION_REASON = (
    "COALESCE(deb.termination_reason, json_extract(dec.decision_json, '$.termination_reason'))"
)


async def get_analytics_overview(db: aiosqlite.Connection, days: int = 0) -> dict[str, Any]:
    """Aggregate overview stats for completed debates, optionally scoped to N days."""
    dc = _date_clause(days, "deb.created_at")
    cur = await db.execute(
        f"""
        SELECT COUNT(*), AVG(deb.current_round), AVG(deb.agreement_score),
               AVG(CASE WHEN {_TERMINATION_REASON} = 'consensus_reached' THEN deb.current_round END)
        {_COMPLETED_DEBATES} {dc}
        """
    )
    row = await cur.fetchone()
    total_debates: int = row[0] if row and row[0] else 0
    avg_rounds = float(row[1]) if row and row[1] is not None else 0.0
    avg_agreement = float(row[2]) if row and row[2] is not None else 0.0
    avg_rounds_to_consensus = float(row[3]) if row and row[3] is not None else None

    cur = await db.execute(
        f"""
        SELECT COALESCE({_TERMINATION_REASON}, 'unknown') AS reason, COUNT(*)
        {_COMPLETED_DEBATES} {dc}
        GROUP BY reason
        """
    )
    rows = await cur.fetchall()
    debates_by_termination: dict[str, int] = {r[0]: r[1] for r in rows}

    # The per-day chart covers the selected range, or the last 30 days for "all time".
    trend_days = days if days and days > 0 else 30
    cur = await db.execute(
        f"""
        SELECT DATE(deb.created_at) AS day, COUNT(*) AS cnt
        {_COMPLETED_DEBATES} {_date_clause(trend_days, "deb.created_at")}
        GROUP BY day
        ORDER BY day ASC
        """
    )
    rows = await cur.fetchall()
    debates_per_day = [{"date": r[0], "count": r[1]} for r in rows]

    return {
        "total_debates": total_debates,
        "avg_rounds": round(avg_rounds, 2),
        "avg_rounds_to_consensus": (
            round(avg_rounds_to_consensus, 2) if avg_rounds_to_consensus is not None else None
        ),
        "avg_agreement_score": round(avg_agreement, 3),
        "debates_by_termination": debates_by_termination,
        "debates_per_day": debates_per_day,
        "trend_days": trend_days,
    }


def _final_positions(state: dict[str, Any]) -> dict[str, str]:
    """Each agent's position in the last round that has any."""
    for round_data in reversed(state.get("rounds") or []):
        positions = {
            out.get("agent_name"): out.get("position")
            for out in round_data.get("agent_outputs") or []
            if out.get("agent_name") and out.get("position")
        }
        if positions:
            return positions
    return {}


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
    pair_agreement: dict[tuple[str, str], list[float]] = {}

    for row in state_rows:
        try:
            state = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            continue

        final_conf: dict[str, float] = state.get("confidence_scores", {})
        for agent, score in final_conf.items():
            confidence_sums.setdefault(agent, []).append(float(score))

        positions = _final_positions(state)
        names = sorted(positions)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                pair_agreement.setdefault((a, b), []).append(
                    normalize_position_overlap(
                        _word_overlap(positions[a], positions[b]),
                        settings.POSITION_OVERLAP_FLOOR,
                        settings.POSITION_OVERLAP_CEILING,
                    )
                )

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

    # Pairwise agreement: how alike two agents' final positions were, averaged over
    # the debates both took part in, on the same 0–1 scale as the consensus gate.
    # Symmetric; None for a pair that never debated together.
    matrix_agents = sorted({name for pair in pair_agreement for name in pair})
    matrix: dict[str, dict[str, float | None]] = {}
    for a in matrix_agents:
        matrix[a] = {}
        for b in matrix_agents:
            if a == b:
                matrix[a][b] = 1.0
                continue
            scores = pair_agreement.get((min(a, b), max(a, b)))
            matrix[a][b] = round(sum(scores) / len(scores), 3) if scores else None

    return {"agents": agent_stats, "agreement_matrix": matrix}


# Legacy fallback: debates written before `mode` was persisted on the state
# inferred the preset from the round count. New debates store `mode` directly.
_LEGACY_MODE_BY_ROUNDS = {2: "quick", 4: "standard", 6: "thorough"}


def _mode_label(state: dict[str, Any]) -> str:
    """Mode a debate ran in — the persisted ``mode``, or inferred from ``max_rounds``
    for legacy records written before the mode was stored on the state."""
    mode = state.get("mode")
    if mode:
        return str(mode)
    return _LEGACY_MODE_BY_ROUNDS.get(state.get("max_rounds", 4), "custom")


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

    # Mode and domain-pack breakdowns both come from the persisted state, so we
    # read it once. Mode is taken from the stored `mode` (or inferred from the
    # round count for legacy rows) rather than guessing — the two no longer
    # correspond now that round count is user-adjustable.
    cur = await db.execute(
        f"""
        SELECT state_json FROM debates
        WHERE status IN ('converged', 'max_rounds_reached') AND state_json IS NOT NULL {dc}
        """
    )
    rows = await cur.fetchall()
    mode_breakdown: dict[str, int] = {}
    domain_pack_counts: dict[str, int] = {}
    for row in rows:
        try:
            state = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            continue
        label = _mode_label(state)
        mode_breakdown[label] = mode_breakdown.get(label, 0) + 1
        pack = state.get("domain_pack") or "default"
        domain_pack_counts[pack] = domain_pack_counts.get(pack, 0) + 1

    return {
        "avg_agreement_by_round": avg_agreement_by_round,
        "mode_breakdown": mode_breakdown,
        "domain_pack_breakdown": domain_pack_counts,
    }


_TEMPLATE_TITLES = {t.id: t.title for t in TEMPLATES}


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

        # Only debates started from a built-in template count towards template stats.
        template_id = state.get("template_id")
        if template_id:
            template = _TEMPLATE_TITLES.get(template_id, template_id)
            template_scores.setdefault(template, []).append(quality)

        mode = _mode_label(state)
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
