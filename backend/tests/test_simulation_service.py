"""
Phase 6.4 — Simulation service tests.

Tests the run_simulation business logic: stability rating thresholds,
consistency_score, variance, stable_risk_flags, and SimulationResult schema.
All DebateGraph calls are mocked — no real LLM needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


def _make_decision(thread_id: str, decision_text: str, agreement: float, flags: list[str]) -> FinalDecision:
    return FinalDecision(
        thread_id=thread_id,
        query="Should we expand?",
        decision=decision_text,
        rationale_summary="Some rationale.",
        confidence_score=agreement,
        agreement_score=agreement,
        risk_flags=flags,
        total_rounds=2,
        termination_reason="consensus_reached",
    )


async def _mock_run_simulation(query, runs, max_rounds, mode, llm_client, settings):
    """Import lazily to avoid triggering app startup at module load."""
    from app.services.simulation import run_simulation  # noqa: PLC0415
    return await run_simulation(
        query=query,
        runs=runs,
        max_rounds=max_rounds,
        mode=mode,
        llm_client=llm_client,
        settings=settings,
    )


class TestSimulationService:

    @pytest.mark.anyio
    async def test_run_simulation_returns_simulation_result(self):
        from app.services.simulation import run_simulation  # noqa: PLC0415

        decision = _make_decision("t1", "Proceed.", 0.85, ["currency"])
        state = DebateState(user_query="Should we expand?")
        state.termination_reason = "consensus_reached"

        with patch("app.services.simulation.DebateGraph") as MockGraph:
            instance = MagicMock()
            instance.run = AsyncMock(return_value=(state, decision))
            MockGraph.return_value = instance

            result = await run_simulation(
                query="Should we expand?",
                runs=2,
                max_rounds=2,
                mode="standard",
                llm_client=MagicMock(),
                settings=MagicMock(
                    MAX_DEBATE_ROUNDS=4,
                    CONSENSUS_THRESHOLD=0.75,
                    CHECKPOINT_DATABASE_URL=":memory:",
                    HITL_ENABLED=False,
                    SEMANTIC_CONSENSUS_ENABLED=False,
                    KNOWLEDGE_BASE_DIR="knowledge_base",
                ),
            )

        assert result.runs == 2
        assert len(result.decisions) == 2
        assert result.stability_rating in {"High", "Medium", "Low"}

    @pytest.mark.anyio
    async def test_stability_rating_high_when_consistent(self):
        from app.services.simulation import run_simulation  # noqa: PLC0415

        same_text = "Proceed with phased expansion into Asia."
        decisions = [
            _make_decision(f"t{i}", same_text, 0.88, ["currency"]) for i in range(3)
        ]
        states = [DebateState(user_query="Q?") for _ in decisions]
        for s in states:
            s.termination_reason = "consensus_reached"

        with patch("app.services.simulation.DebateGraph") as MockGraph:
            instance = MagicMock()
            instance.run = AsyncMock(side_effect=list(zip(states, decisions)))
            MockGraph.return_value = instance

            result = await run_simulation(
                query="Should we expand?",
                runs=3,
                max_rounds=2,
                mode="quick",
                llm_client=MagicMock(),
                settings=MagicMock(
                    MAX_DEBATE_ROUNDS=2,
                    CONSENSUS_THRESHOLD=0.75,
                    CHECKPOINT_DATABASE_URL=":memory:",
                    HITL_ENABLED=False,
                    SEMANTIC_CONSENSUS_ENABLED=False,
                    KNOWLEDGE_BASE_DIR="knowledge_base",
                ),
            )

        assert result.stability_rating == "High"

    @pytest.mark.anyio
    async def test_stable_risk_flags_appear_in_majority_of_runs(self):
        from app.services.simulation import run_simulation  # noqa: PLC0415

        decisions = [
            _make_decision("t1", "Proceed.", 0.8, ["currency", "regulatory"]),
            _make_decision("t2", "Proceed.", 0.75, ["currency", "market"]),
            _make_decision("t3", "Proceed.", 0.82, ["currency"]),
        ]
        states = [DebateState(user_query="Q?") for _ in decisions]
        for s in states:
            s.termination_reason = "consensus_reached"

        with patch("app.services.simulation.DebateGraph") as MockGraph:
            instance = MagicMock()
            instance.run = AsyncMock(side_effect=list(zip(states, decisions)))
            MockGraph.return_value = instance

            result = await run_simulation(
                query="Q?",
                runs=3,
                max_rounds=2,
                mode="quick",
                llm_client=MagicMock(),
                settings=MagicMock(
                    MAX_DEBATE_ROUNDS=2,
                    CONSENSUS_THRESHOLD=0.75,
                    CHECKPOINT_DATABASE_URL=":memory:",
                    HITL_ENABLED=False,
                    SEMANTIC_CONSENSUS_ENABLED=False,
                    KNOWLEDGE_BASE_DIR="knowledge_base",
                ),
            )

        assert "currency" in result.stable_risk_flags
        assert "market" not in result.stable_risk_flags

    @pytest.mark.anyio
    async def test_result_has_required_schema_fields(self):
        from app.services.simulation import run_simulation, SimulationResult  # noqa: PLC0415

        decision = _make_decision("t1", "Proceed.", 0.85, [])
        state = DebateState(user_query="Q?")
        state.termination_reason = "consensus_reached"

        with patch("app.services.simulation.DebateGraph") as MockGraph:
            instance = MagicMock()
            instance.run = AsyncMock(return_value=(state, decision))
            MockGraph.return_value = instance

            result = await run_simulation(
                query="Q?",
                runs=2,
                max_rounds=2,
                mode="quick",
                llm_client=MagicMock(),
                settings=MagicMock(
                    MAX_DEBATE_ROUNDS=2,
                    CONSENSUS_THRESHOLD=0.75,
                    CHECKPOINT_DATABASE_URL=":memory:",
                    HITL_ENABLED=False,
                    SEMANTIC_CONSENSUS_ENABLED=False,
                    KNOWLEDGE_BASE_DIR="knowledge_base",
                ),
            )

        assert isinstance(result, SimulationResult)
        assert 0.0 <= result.consistency_score <= 1.0
        assert result.confidence_variance >= 0.0
        assert isinstance(result.stable_risk_flags, list)
