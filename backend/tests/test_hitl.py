"""
Phase 6.4 — HITL node tests (B2 fix verification).

Tests make_hitl_node: approve, override, add_round actions,
and verifies debate_state status transitions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.nodes import make_hitl_node
from app.orchestrator.lg_state import DebateGraphState
from app.schemas.state import DebateRound, DebateState


def _make_state(overrides: dict | None = None) -> DebateGraphState:
    ds = DebateState(user_query="Should we expand into Asia?", current_round=1, max_rounds=3)
    ds.status = "awaiting_approval"
    ds.termination_reason = "consensus_reached"
    ds.rounds.append(DebateRound(round_number=1))
    payload = {
        "round_number": 1,
        "agreement_score": 0.78,
        "termination_reason": "consensus_reached",
        "synthesis_summary": "Good progress.",
        "options": ["approve", "override", "add_round"],
    }
    state: DebateGraphState = {
        "debate_state": ds,
        "should_continue": False,
        "final_decision": None,
        "skip_critique_phase": False,
        "consensus_threshold": None,
        "hitl_mode": True,
        "awaiting_approval": True,
        "hitl_interrupt_payload": payload,
    }
    if overrides:
        state.update(overrides)  # type: ignore[arg-type]
    return state


class TestHITLNode:

    @pytest.mark.anyio
    async def test_approve_sets_should_continue_false(self):
        emit = MagicMock()
        persist = AsyncMock()

        with patch("app.orchestrator.nodes.interrupt", return_value={"action": "approve", "feedback": ""}):
            node = make_hitl_node(emit, persist)
            result = await node(_make_state())

        assert result["should_continue"] is False

    @pytest.mark.anyio
    async def test_override_sets_human_feedback_and_stops(self):
        emit = MagicMock()
        persist = AsyncMock()

        with patch("app.orchestrator.nodes.interrupt", return_value={"action": "override", "feedback": "Reconsider risk."}):
            node = make_hitl_node(emit, persist)
            result = await node(_make_state())

        ds: DebateState = result["debate_state"]
        assert ds.human_feedback == "Reconsider risk."
        assert ds.termination_reason == "human_override"
        assert result["should_continue"] is False

    @pytest.mark.anyio
    async def test_add_round_increments_max_rounds_and_continues(self):
        emit = MagicMock()
        persist = AsyncMock()

        with patch("app.orchestrator.nodes.interrupt", return_value={"action": "add_round", "feedback": ""}):
            node = make_hitl_node(emit, persist)
            result = await node(_make_state())

        ds: DebateState = result["debate_state"]
        assert ds.max_rounds == 4  # original was 3
        assert result["should_continue"] is True

    @pytest.mark.anyio
    async def test_status_set_to_awaiting_before_interrupt(self):
        """debate_state.status must be 'awaiting_approval' when persist is called."""
        emit = MagicMock()
        captured = []

        async def capturing_persist(state):
            captured.append(state.status)

        with patch("app.orchestrator.nodes.interrupt", return_value={"action": "approve", "feedback": ""}):
            node = make_hitl_node(emit, capturing_persist)
            await node(_make_state())

        assert captured[0] == "awaiting_approval"

    @pytest.mark.anyio
    async def test_status_restored_to_in_progress_after_approval(self):
        emit = MagicMock()
        persist = AsyncMock()

        with patch("app.orchestrator.nodes.interrupt", return_value={"action": "approve", "feedback": ""}):
            node = make_hitl_node(emit, persist)
            result = await node(_make_state())

        ds: DebateState = result["debate_state"]
        assert ds.status == "in_progress"

    @pytest.mark.anyio
    async def test_hitl_payload_cleared_in_return(self):
        emit = MagicMock()
        persist = AsyncMock()

        with patch("app.orchestrator.nodes.interrupt", return_value={"action": "approve", "feedback": ""}):
            node = make_hitl_node(emit, persist)
            result = await node(_make_state())

        assert result["hitl_interrupt_payload"] is None

    @pytest.mark.anyio
    async def test_non_dict_resume_defaults_to_approve(self):
        """If interrupt returns a non-dict (e.g. LangGraph v0.2 compat), default to approve."""
        emit = MagicMock()
        persist = AsyncMock()

        with patch("app.orchestrator.nodes.interrupt", return_value=None):
            node = make_hitl_node(emit, persist)
            result = await node(_make_state())

        assert result["should_continue"] is False
