"""
A HITL "add round" must never push a debate past the schema's round limit:
such a state could no longer be loaded (status polls / recovery would 500).
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_debate_store
from app.main import app
from app.orchestrator.nodes import _hitl_options, make_hitl_node
from app.schemas.state import MAX_DEBATE_ROUNDS_LIMIT, DebateRound, DebateState
from tests.test_hitl import _make_state


def test_add_round_is_offered_only_below_the_limit():
    below = DebateState(user_query="Should we expand into Asia?", max_rounds=MAX_DEBATE_ROUNDS_LIMIT - 1)
    at_limit = DebateState(user_query="Should we expand into Asia?", max_rounds=MAX_DEBATE_ROUNDS_LIMIT)
    assert "add_round" in _hitl_options(below)
    assert _hitl_options(at_limit) == ["approve", "override"]


@pytest.mark.anyio
async def test_hitl_node_never_exceeds_the_limit():
    graph_state = _make_state()
    ds = graph_state["debate_state"]
    ds.max_rounds = MAX_DEBATE_ROUNDS_LIMIT
    node = make_hitl_node(lambda *_: None)

    with patch("app.orchestrator.nodes.interrupt", return_value={"action": "add_round", "feedback": ""}):
        result = await node(graph_state)

    assert result["debate_state"].max_rounds == MAX_DEBATE_ROUNDS_LIMIT
    assert result["should_continue"] is False
    # The state still round-trips through validation (status polls, recovery).
    DebateState.model_validate_json(result["debate_state"].model_dump_json())


@pytest.mark.anyio
async def test_approve_rejects_add_round_at_the_limit():
    paused = DebateState(
        user_query="Should we expand into Asia?",
        status="awaiting_approval",
        current_round=MAX_DEBATE_ROUNDS_LIMIT,
        max_rounds=MAX_DEBATE_ROUNDS_LIMIT,
        rounds=[DebateRound(round_number=i + 1) for i in range(MAX_DEBATE_ROUNDS_LIMIT)],
    )
    store = {paused.thread_id: paused}
    app.dependency_overrides[get_debate_store] = lambda: store
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
            resp = await client.post(f"/debate/{paused.thread_id}/approve", json={"action": "add_round"})
    finally:
        app.dependency_overrides.pop(get_debate_store, None)

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "round_limit_reached"
    assert paused.status == "awaiting_approval"  # untouched
