"""
Analytics numbers must describe the stored debates correctly: consensus-only
round averages, termination reasons for older rows, a symmetric agreement
matrix built from positions, real template stats, the Custom mode, and a cache
that is cleared when new results land.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.analytics import invalidate_analytics_cache
from app.api.dependencies import get_groq_client
from app.api.routes import _persist_debate
from app.core.config import settings
from app.db.crud import (
    get_analytics_agents,
    get_analytics_convergence,
    get_analytics_overview,
    get_analytics_quality,
    save_decision,
    save_evaluation,
    upsert_debate,
)
from app.main import app
from app.schemas.agent_response import AgentResponse
from app.schemas.api_models import DebateStartRequest
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _fresh_cache():
    invalidate_analytics_cache()
    yield
    invalidate_analytics_cache()


def _state(reason: str | None, rounds_run: int, **kwargs) -> DebateState:
    status = "max_rounds_reached" if reason == "max_rounds_reached" else "converged"
    return DebateState(
        user_query="Should we open a second office next year?",
        status=status,
        current_round=rounds_run,
        max_rounds=max(rounds_run, 2),
        termination_reason=reason,
        agreement_score=0.8,
        **kwargs,
    )


def _decision(state: DebateState, reason: str) -> FinalDecision:
    return FinalDecision(
        thread_id=state.thread_id,
        decision="Proceed",
        rationale_summary="why",
        confidence_score=0.8,
        agreement_score=state.agreement_score,
        total_rounds=max(state.current_round, 1),
        termination_reason=reason,
    )


async def _store(state: DebateState, reason: str, legacy_row: bool = False) -> None:
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await upsert_debate(db, state)
        await save_decision(db, _decision(state, reason), state.user_query)
        if legacy_row:
            # Rows written before termination_reason was stored on the debates table.
            await db.execute(
                "UPDATE debates SET termination_reason = NULL WHERE thread_id = ?", (state.thread_id,)
            )
            await db.commit()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_overview_on_empty_db():
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        result = await get_analytics_overview(db)

    assert result["total_debates"] == 0
    assert result["avg_rounds"] == 0.0
    assert result["avg_rounds_to_consensus"] is None
    assert result["debates_by_termination"] == {}
    assert result["debates_per_day"] == []
    assert result["trend_days"] == 30


@pytest.mark.anyio
async def test_rounds_to_consensus_counts_only_consensus_debates():
    await _store(_state("consensus_reached", 1), "consensus_reached")
    await _store(_state("consensus_reached", 2), "consensus_reached", legacy_row=True)
    await _store(_state("max_rounds_reached", 6), "max_rounds_reached")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        result = await get_analytics_overview(db)

    assert result["total_debates"] == 3
    assert result["avg_rounds"] == 3.0
    assert result["avg_rounds_to_consensus"] == 1.5


@pytest.mark.anyio
async def test_older_rows_take_their_termination_reason_from_the_decision():
    await _store(_state("consensus_reached", 1), "consensus_reached", legacy_row=True)
    await _store(_state("consensus_reached", 1), "consensus_reached", legacy_row=True)
    await _store(_state("human_override", 2), "human_override", legacy_row=True)
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        result = await get_analytics_overview(db)

    assert result["debates_by_termination"] == {"consensus_reached": 2, "human_override": 1}


@pytest.mark.anyio
async def test_trend_counts_completed_debates_over_the_selected_range():
    await _store(_state("consensus_reached", 1), "consensus_reached")
    old = _state("consensus_reached", 1, created_at=datetime.now(UTC) - timedelta(days=20))
    await _store(old, "consensus_reached")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await upsert_debate(db, DebateState(user_query="Still running question here", status="in_progress"))
        await upsert_debate(db, DebateState(user_query="A debate that failed midway", status="error"))
        week = await get_analytics_overview(db, days=7)
        month = await get_analytics_overview(db, days=30)

    assert week["trend_days"] == 7
    assert sum(d["count"] for d in week["debates_per_day"]) == 1
    assert sum(d["count"] for d in month["debates_per_day"]) == 2
    assert month["total_debates"] == 2


# ---------------------------------------------------------------------------
# Agreement matrix
# ---------------------------------------------------------------------------

_SHARED = "We should expand into the Southeast Asian market in Q3 with a phased pilot launch"
_ECHO = "We should expand into the Southeast Asian market in Q3 through a phased pilot launch"
_OPPOSED = "Delay everything; regulatory exposure and cash burn make this far too risky now"


def _with_positions(positions: dict[str, str]) -> DebateState:
    outputs = [
        AgentResponse(agent_name=name, round_number=1, position=text, reasoning="r", confidence_score=0.9)
        for name, text in positions.items()
    ]
    return _state("consensus_reached", 1, rounds=[DebateRound(round_number=1, agent_outputs=outputs)])


@pytest.mark.anyio
async def test_agreement_matrix_compares_final_positions_symmetrically():
    await _store(_with_positions({"Analyst": _SHARED, "Strategy": _ECHO, "Risk": _OPPOSED}), "consensus_reached")
    await _store(_with_positions({"Analyst": _SHARED, "Finance": _OPPOSED}), "consensus_reached")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        matrix = (await get_analytics_agents(db))["agreement_matrix"]

    assert matrix["Analyst"]["Strategy"] == matrix["Strategy"]["Analyst"]
    assert matrix["Analyst"]["Strategy"] > 0.9
    assert matrix["Analyst"]["Risk"] < 0.2
    assert matrix["Risk"]["Analyst"] == matrix["Analyst"]["Risk"]
    assert matrix["Analyst"]["Analyst"] == 1.0
    assert matrix["Strategy"]["Finance"] is None  # never in the same debate


# ---------------------------------------------------------------------------
# Modes and templates
# ---------------------------------------------------------------------------

def test_custom_mode_keeps_its_name_and_the_callers_settings():
    req = DebateStartRequest(
        query="Should we rewrite the billing service?", mode="custom", max_rounds=5, consensus_threshold=0.7
    )
    assert (req.mode, req.max_rounds, req.consensus_threshold) == ("custom", 5, 0.7)
    assert (req.min_rounds, req.skip_critique_phase) == (2, False)  # Standard's other settings


@pytest.mark.anyio
async def test_custom_debates_get_their_own_mode_bucket():
    await _store(_state("consensus_reached", 1, mode="custom"), "consensus_reached")
    await _store(_state("consensus_reached", 1, mode="standard"), "consensus_reached")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        result = await get_analytics_convergence(db)

    assert result["mode_breakdown"] == {"custom": 1, "standard": 1}


def test_unknown_template_id_is_dropped_not_fatal():
    req = DebateStartRequest(query="Should we rewrite the billing service?", template_id="no-such-template")
    assert req.template_id is None
    known = DebateStartRequest(query="Should we rewrite the billing service?", template_id="market-expansion")
    assert known.template_id == "market-expansion"


@pytest.mark.anyio
async def test_template_id_is_stored_on_the_debate():
    captured = {}

    async def fake_run(query, initial_state, **_):
        captured["state"] = initial_state
        return initial_state, _decision(initial_state, "consensus_reached")

    graph = MagicMock()
    graph.run = AsyncMock(side_effect=fake_run)
    with patch("app.api.routes.DebateGraph", return_value=graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
            resp = await client.post("/debate/start", json={
                "query": "Should we expand into the Southeast Asian market?",
                "mode": "custom", "max_rounds": 3, "template_id": "market-expansion",
            })

    assert resp.status_code == 200
    assert captured["state"].template_id == "market-expansion"
    assert captured["state"].mode == "custom"


@pytest.mark.anyio
async def test_template_scores_only_cover_template_debates():
    from_template = _state("consensus_reached", 1, template_id="market-expansion", domain_pack="finance")
    free_text = _state("consensus_reached", 1, domain_pack="finance")
    await _store(from_template, "consensus_reached")
    await _store(free_text, "consensus_reached")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await save_evaluation(db, from_template.thread_id, '{"overall": 0.9}')
        await save_evaluation(db, free_text.thread_id, '{"overall": 0.5}')
        result = await get_analytics_quality(db)

    assert result["evaluated_count"] == 2
    assert result["scores_by_template"] == {"Market Expansion": 0.9}
    assert result["best_performing_templates"] == ["Market Expansion"]
    assert result["scores_by_domain_pack"] == {"finance": 0.7}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cache_is_cleared_when_a_debate_is_stored_or_evaluated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        assert (await client.get("/analytics/overview")).json()["total_debates"] == 0

        state = _state("consensus_reached", 1)
        assert await _persist_debate(state, _decision(state, "consensus_reached"), settings.DATABASE_URL)
        assert (await client.get("/analytics/overview")).json()["total_debates"] == 1

        assert (await client.get("/analytics/quality")).json()["evaluated_count"] == 0
        evaluation = MagicMock()
        evaluation.model_dump_json.return_value = '{"overall": 0.8}'
        app.dependency_overrides[get_groq_client] = lambda: MagicMock()
        try:
            with patch("app.services.evaluator.evaluate_decision", AsyncMock(return_value=evaluation)):
                assert (await client.post(f"/decision/{state.thread_id}/evaluate")).status_code == 200
        finally:
            app.dependency_overrides.pop(get_groq_client, None)
        assert (await client.get("/analytics/quality")).json()["evaluated_count"] == 1
