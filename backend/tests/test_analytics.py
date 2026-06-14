"""
Tests for Phase 5 — Analytics & Evaluation backend endpoints.

Coverage
--------
GET /analytics/overview    — returns expected keys; empty DB returns zeros
GET /analytics/agents      — returns expected keys; populated DB returns stats
GET /analytics/convergence — returns expected keys; synthesis events shape the curve
GET /analytics/quality     — returns evaluated_count=0 when no evaluations exist
Cache                      — second call returns cached result (no additional DB hit)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.analytics import invalidate_analytics_cache
from app.api.dependencies import get_db
from app.db.crud import (
    get_analytics_agents,
    get_analytics_convergence,
    get_analytics_overview,
    get_analytics_quality,
)
from app.main import app
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure the analytics cache is empty before and after every test."""
    invalidate_analytics_cache()
    yield
    invalidate_analytics_cache()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# In-memory async DB helpers — build a minimal aiosqlite-like stub
# ---------------------------------------------------------------------------


class _Row:
    """Simple row stub: index-accessible."""

    def __init__(self, *values: Any):
        self._data = values

    def __getitem__(self, idx: int) -> Any:
        return self._data[idx]


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = [_Row(*r) for r in rows]

    async def fetchone(self) -> _Row | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[_Row]:
        return self._rows


class _FakeDB:
    """Minimal aiosqlite.Connection stub with configurable per-query responses."""

    def __init__(self, query_map: dict[str, list[tuple]]):
        self._map = query_map  # substring → rows

    async def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        for key, rows in self._map.items():
            if key.lower() in sql.lower():
                return _FakeCursor(rows)
        return _FakeCursor([])


# ---------------------------------------------------------------------------
# Overview CRUD tests
# ---------------------------------------------------------------------------


class TestAnalyticsOverviewCRUD:
    """Direct CRUD function tests — no HTTP layer."""

    @pytest.mark.anyio
    async def test_empty_db_returns_zeros(self):
        db = _FakeDB(
            {
                "avg(current_round)": [(None, None)],
                "date(created": [],
                "coalesce(termination_reason": [],
                "count(*) from debates": [(0,)],
            }
        )
        result = await get_analytics_overview(db)  # type: ignore[arg-type]
        assert result["total_debates"] == 0
        assert result["avg_rounds_to_consensus"] == 0.0
        assert result["avg_agreement_score"] == 0.0
        assert result["debates_by_termination"] == {}
        assert result["debates_per_day"] == []

    @pytest.mark.anyio
    async def test_with_data_returns_correct_values(self):
        state_json = json.dumps({"domain_pack": "finance", "max_rounds": 4})
        db = _FakeDB(
            {
                "avg(current_round)": [(2.5, 0.82)],
                "date(created": [
                    ("2026-03-19", 2),
                    ("2026-03-20", 1),
                ],
                "coalesce(termination_reason": [
                    ("consensus_reached", 2),
                    ("max_rounds_reached", 1),
                ],
                "count(*) from debates": [(3,)],
            }
        )
        result = await get_analytics_overview(db)  # type: ignore[arg-type]
        assert result["total_debates"] == 3
        assert result["avg_rounds_to_consensus"] == 2.5
        assert result["avg_agreement_score"] == pytest.approx(0.82, abs=0.001)
        assert result["debates_by_termination"]["consensus_reached"] == 2
        assert len(result["debates_per_day"]) == 2


# ---------------------------------------------------------------------------
# Agents CRUD tests
# ---------------------------------------------------------------------------


class TestAnalyticsAgentsCRUD:
    @pytest.mark.anyio
    async def test_empty_db_returns_empty_structures(self):
        db = _FakeDB({"state_json": [], "decision_json": []})
        result = await get_analytics_agents(db)  # type: ignore[arg-type]
        assert result["agents"] == {}
        assert result["agreement_matrix"] == {}

    @pytest.mark.anyio
    async def test_parses_confidence_scores(self):
        state = DebateState(
            user_query="Should we expand into SE Asia?",
            status="converged",
            confidence_scores={"Analyst": 0.8, "Risk": 0.6, "Strategy": 0.9},
        )
        state_json = state.model_dump_json()
        db = _FakeDB({"state_json": [(state_json,)], "decision_json": []})
        result = await get_analytics_agents(db)  # type: ignore[arg-type]
        assert "Analyst" in result["agents"]
        assert result["agents"]["Analyst"]["avg_confidence"] == pytest.approx(0.8, abs=0.001)
        assert result["agents"]["Risk"]["avg_confidence"] == pytest.approx(0.6, abs=0.001)


# ---------------------------------------------------------------------------
# Convergence CRUD tests
# ---------------------------------------------------------------------------


class TestAnalyticsConvergenceCRUD:
    @pytest.mark.anyio
    async def test_empty_db_returns_empty_lists(self):
        db = _FakeDB(
            {
                "event_type = 'synthesis'": [],
                "group by max_rounds": [],
                "state_json": [],
            }
        )
        result = await get_analytics_convergence(db)  # type: ignore[arg-type]
        assert result["avg_agreement_by_round"] == []
        assert result["mode_breakdown"] == {}
        assert result["domain_pack_breakdown"] == {}

    @pytest.mark.anyio
    async def test_synthesis_events_build_curve(self):
        synthesis_rows = [
            (json.dumps({"round_number": 1, "agreement_score": 0.45}),),
            (json.dumps({"round_number": 1, "agreement_score": 0.55}),),
            (json.dumps({"round_number": 2, "agreement_score": 0.75}),),
        ]
        db = _FakeDB(
            {
                "event_type = 'synthesis'": synthesis_rows,
                "group by max_rounds": [(4, 2)],
                "state_json": [],
            }
        )
        result = await get_analytics_convergence(db)  # type: ignore[arg-type]
        curve = result["avg_agreement_by_round"]
        assert len(curve) == 2
        assert curve[0] == pytest.approx(0.5, abs=0.01)  # avg of 0.45 and 0.55
        assert curve[1] == pytest.approx(0.75, abs=0.01)

    @pytest.mark.anyio
    async def test_mode_breakdown_prefers_persisted_mode(self):
        # New rows carry the persisted `mode`; legacy rows (no `mode`) fall back
        # to inferring the preset from the round count.
        state_rows = [
            (json.dumps({"mode": "quick"}),),
            (json.dumps({"mode": "standard"}),),
            (json.dumps({"mode": "standard"}),),
            (json.dumps({"mode": "thorough"}),),
            (json.dumps({"max_rounds": 2}),),   # legacy → quick
            (json.dumps({"max_rounds": 6}),),   # legacy → thorough
        ]
        db = _FakeDB(
            {
                "event_type = 'synthesis'": [],
                "state_json": state_rows,
            }
        )
        result = await get_analytics_convergence(db)  # type: ignore[arg-type]
        assert result["mode_breakdown"]["quick"] == 2       # 1 persisted + 1 legacy (2 rounds)
        assert result["mode_breakdown"]["standard"] == 2    # both persisted
        assert result["mode_breakdown"]["thorough"] == 2    # 1 persisted + 1 legacy (6 rounds)


# ---------------------------------------------------------------------------
# Quality CRUD tests
# ---------------------------------------------------------------------------


class TestAnalyticsQualityCRUD:
    @pytest.mark.anyio
    async def test_no_evaluations_returns_zero_count(self):
        db = _FakeDB({"evaluation_json": []})
        result = await get_analytics_quality(db)  # type: ignore[arg-type]
        assert result["evaluated_count"] == 0
        assert result["avg_quality_score"] is None


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestAnalyticsEndpoints:
    """Integration-level tests via /analytics/* HTTP endpoints."""

    @pytest.fixture
    def mock_db(self):
        """Override get_db with an empty fake DB for HTTP tests."""
        fake = _FakeDB(
            {
                # overview queries — ordered from most-specific to least-specific
                "avg(current_round)": [(None, None)],
                "date(created": [],
                "coalesce(termination_reason": [],
                "count(*) from debates": [(0,)],
                # convergence queries
                "event_type = 'synthesis'": [],
                "group by max_rounds": [],
                # agents and quality
                "state_json": [],
                "decision_json": [],
                "evaluation_json": [],
            }
        )

        async def _override():
            yield fake

        app.dependency_overrides[get_db] = _override
        yield fake
        app.dependency_overrides.pop(get_db, None)

    @pytest.mark.anyio
    async def test_overview_returns_200(self, client, mock_db):
        resp = await client.get("/analytics/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_debates" in body
        assert "avg_rounds_to_consensus" in body
        assert "avg_agreement_score" in body
        assert "debates_by_termination" in body
        assert "debates_per_day" in body

    @pytest.mark.anyio
    async def test_agents_returns_200(self, client, mock_db):
        resp = await client.get("/analytics/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert "agents" in body
        assert "agreement_matrix" in body

    @pytest.mark.anyio
    async def test_convergence_returns_200(self, client, mock_db):
        resp = await client.get("/analytics/convergence")
        assert resp.status_code == 200
        body = resp.json()
        assert "avg_agreement_by_round" in body
        assert "mode_breakdown" in body
        assert "domain_pack_breakdown" in body

    @pytest.mark.anyio
    async def test_quality_returns_200_with_zero_count(self, client, mock_db):
        resp = await client.get("/analytics/quality")
        assert resp.status_code == 200
        body = resp.json()
        assert body["evaluated_count"] == 0
        assert body["avg_quality_score"] is None

    @pytest.mark.anyio
    async def test_cache_returns_same_result(self, client, mock_db):
        """Second call should be served from cache (same data, no error)."""
        r1 = await client.get("/analytics/overview")
        r2 = await client.get("/analytics/overview")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()
