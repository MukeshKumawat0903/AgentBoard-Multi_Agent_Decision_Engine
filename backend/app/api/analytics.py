"""
Analytics API endpoints for AgentBoard — Phase 5.1.

Endpoints
---------
GET /analytics/overview     — aggregate debate statistics
GET /analytics/agents       — per-agent performance stats
GET /analytics/convergence  — convergence curves and breakdowns
GET /analytics/quality      — decision quality scores (when evaluations exist)

All four responses are cached for 5 minutes to keep SQLite load low.
The cache can be cleared via ``invalidate_analytics_cache()`` (used in tests).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends

from app.api.dependencies import get_db
from app.db.crud import (
    get_analytics_agents,
    get_analytics_convergence,
    get_analytics_overview,
    get_analytics_quality,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("agentboard.analytics")

# ---------------------------------------------------------------------------
# 5-minute in-process cache
# ---------------------------------------------------------------------------

_CACHE_TTL: float = 300.0  # seconds
_cache: dict[str, tuple[float, Any]] = {}


def _get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is not None and time.monotonic() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


def invalidate_analytics_cache() -> None:
    """Clear all cached analytics responses.  Called from tests and startup."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    summary="Aggregate debate statistics",
    response_description="Overview stats: totals, averages, per-day trend",
)
async def analytics_overview(db: aiosqlite.Connection = Depends(get_db)) -> dict:
    """
    Returns:
    - ``total_debates`` — count of all completed debates
    - ``avg_rounds_to_consensus`` — mean round count across completed debates
    - ``avg_agreement_score`` — mean final agreement score
    - ``debates_by_termination`` — count grouped by termination_reason
    - ``debates_per_day`` — list of ``{date, count}`` for the last 30 days
    """
    cached = _get("overview")
    if cached is not None:
        logger.debug("analytics_cache_hit", extra={"key": "overview"})
        return cached
    result = await get_analytics_overview(db)
    _set("overview", result)
    return result


@router.get(
    "/agents",
    summary="Per-agent performance statistics",
    response_description="Agent confidence, critique severity, contribution scores, agreement matrix",
)
async def analytics_agents(db: aiosqlite.Connection = Depends(get_db)) -> dict:
    """
    Returns:
    - ``agents`` — dict keyed by agent name with avg_confidence,
      avg_critique_severity_given, avg_contribution_score
    - ``agreement_matrix`` — pairwise co-high-confidence frequency
    """
    cached = _get("agents")
    if cached is not None:
        logger.debug("analytics_cache_hit", extra={"key": "agents"})
        return cached
    result = await get_analytics_agents(db)
    _set("agents", result)
    return result


@router.get(
    "/convergence",
    summary="Convergence curve and mode/domain breakdown",
    response_description="Round-by-round agreement averages and categorical breakdowns",
)
async def analytics_convergence(db: aiosqlite.Connection = Depends(get_db)) -> dict:
    """
    Returns:
    - ``avg_agreement_by_round`` — list of mean agreement scores per round
    - ``mode_breakdown`` — count by debate mode (quick/standard/thorough)
    - ``domain_pack_breakdown`` — count by domain pack
    """
    cached = _get("convergence")
    if cached is not None:
        logger.debug("analytics_cache_hit", extra={"key": "convergence"})
        return cached
    result = await get_analytics_convergence(db)
    _set("convergence", result)
    return result


@router.get(
    "/quality",
    summary="Decision quality score analytics",
    response_description="Quality scores by template, mode, and domain pack (requires evaluations)",
)
async def analytics_quality(db: aiosqlite.Connection = Depends(get_db)) -> dict:
    """
    Returns aggregate quality scores derived from stored evaluation JSON blobs.
    Returns ``evaluated_count: 0`` if no evaluations have been run yet.

    Returns:
    - ``evaluated_count`` — number of evaluated decisions
    - ``avg_quality_score`` — overall mean quality score
    - ``scores_by_template`` / ``scores_by_mode`` / ``scores_by_domain_pack``
    - ``best_performing_templates`` / ``worst_performing_templates``
    """
    cached = _get("quality")
    if cached is not None:
        logger.debug("analytics_cache_hit", extra={"key": "quality"})
        return cached
    result = await get_analytics_quality(db)
    _set("quality", result)
    return result
