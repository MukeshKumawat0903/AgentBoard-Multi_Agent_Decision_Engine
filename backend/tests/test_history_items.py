"""
History rows must describe what actually happened in the debate: rounds that
were run (not the configured maximum) and the real termination reason, with
fallbacks taken from the stored decision instead of invented defaults.
"""

import aiosqlite
import pytest

from app.core.config import settings
from app.db.crud import get_history, save_decision, upsert_debate
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


def _decision(thread_id: str, **overrides) -> FinalDecision:
    data = dict(
        thread_id=thread_id,
        decision="Proceed",
        rationale_summary="why",
        confidence_score=0.8,
        agreement_score=0.71,
        total_rounds=1,
        termination_reason="consensus_reached",
    )
    data.update(overrides)
    return FinalDecision(**data)


@pytest.mark.anyio
async def test_history_reports_rounds_run_not_max_rounds():
    state = DebateState(
        user_query="Should we open a second office?",
        current_round=1,
        max_rounds=4,
        status="converged",
        termination_reason="consensus_reached",
        agreement_score=0.8,
    )
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await upsert_debate(db, state)
        await save_decision(db, _decision(state.thread_id), state.user_query)
        items, total = await get_history(db)

    assert total == 1
    assert items[0]["total_rounds"] == 1
    assert items[0]["termination_reason"] == "consensus_reached"


@pytest.mark.anyio
async def test_human_override_is_reported_as_such():
    state = DebateState(
        user_query="Which vendor should we pick?",
        current_round=2,
        max_rounds=2,
        status="converged",
        termination_reason="human_override",
    )
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await upsert_debate(db, state)
        await save_decision(
            db, _decision(state.thread_id, termination_reason="human_override", total_rounds=2),
            state.user_query,
        )
        items, _ = await get_history(db)

    assert items[0]["termination_reason"] == "human_override"
    assert items[0]["status"] == "converged"


@pytest.mark.anyio
async def test_missing_debate_row_falls_back_to_the_stored_decision():
    """Without a debates row the values come from decision_json, not hard-coded guesses."""
    decision = _decision(
        "orphan-thread", termination_reason="max_rounds_reached", total_rounds=3, agreement_score=0.42
    )
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await save_decision(db, decision, "Should we migrate to Kubernetes?")
        items, _ = await get_history(db)

    item = items[0]
    assert item["total_rounds"] == 3
    assert item["termination_reason"] == "max_rounds_reached"
    assert item["status"] == "max_rounds_reached"
    assert item["agreement_score"] == pytest.approx(0.42)
