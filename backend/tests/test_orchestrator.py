"""Tests for the current LangGraph orchestrator and node factories."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base_agent import BaseAgent
from app.agents.moderator_agent import ModeratorSynthesis
from app.orchestrator.debate_graph import DebateGraph
from app.orchestrator.lg_state import DebateGraphState
from app.orchestrator.nodes import (
    make_convergence_node,
    make_critiques_node,
    make_finalize_node,
    make_proposals_node,
    make_revisions_node,
)
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState


def _mock_settings(
    *,
    max_rounds: int = 4,
    consensus_threshold: float = 0.75,
    semantic_enabled: bool = False,
) -> MagicMock:
    settings = MagicMock()
    settings.MAX_DEBATE_ROUNDS = max_rounds
    settings.CONSENSUS_THRESHOLD = consensus_threshold
    settings.SEMANTIC_CONSENSUS_ENABLED = semantic_enabled
    settings.SEMANTIC_MODEL = "all-MiniLM-L6-v2"
    settings.SEMANTIC_CONSENSUS_WEIGHT = 0.5
    settings.CHECKPOINT_DATABASE_URL = ":memory:"
    return settings


def _mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.ainvoke_structured = AsyncMock()
    return llm


def _agent_response(name: str, round_number: int = 1, confidence: float = 0.8) -> AgentResponse:
    return AgentResponse(
        agent_name=name,
        round_number=round_number,
        position=f"{name} recommends proceeding.",
        reasoning="Solid support.",
        confidence_score=confidence,
    )


def _critique_response(critic: str, target: str, round_number: int = 1) -> CritiqueResponse:
    return CritiqueResponse(
        critic_agent=critic,
        target_agent=target,
        round_number=round_number,
        critique_points=["Needs more detail"],
        severity="low",
        confidence_score=0.7,
    )


def _synthesis(agreement_score: float = 0.8, should_continue: bool = False) -> ModeratorSynthesis:
    return ModeratorSynthesis(
        summary="Broad agreement reached.",
        agreement_areas=["Timing"],
        disagreement_areas=[],
        agreement_score=agreement_score,
        should_continue=should_continue,
        next_round_focus=None,
    )


def _final_decision(state: DebateState) -> FinalDecision:
    return FinalDecision(
        thread_id=state.thread_id,
        query=state.user_query,
        decision="Proceed with phased expansion.",
        rationale_summary="Consensus after debate.",
        confidence_score=0.85,
        agreement_score=state.agreement_score,
        total_rounds=max(1, state.current_round),
        termination_reason=state.termination_reason or "consensus_reached",
        debate_trace=[],
    )


@asynccontextmanager
async def _fake_saver_context() -> AsyncIterator[MagicMock]:
    saver = MagicMock()
    saver.setup = AsyncMock()
    yield saver


@asynccontextmanager
async def _fake_saver_with_checkpoint() -> AsyncIterator[MagicMock]:
    """Context manager whose saver reports an existing checkpoint."""
    saver = MagicMock()
    saver.setup = AsyncMock()
    saver.aget_tuple = AsyncMock(return_value=MagicMock())  # checkpoint present
    yield saver


@asynccontextmanager
async def _fake_saver_no_checkpoint() -> AsyncIterator[MagicMock]:
    """Context manager whose saver reports no checkpoint (returns None)."""
    saver = MagicMock()
    saver.setup = AsyncMock()
    saver.aget_tuple = AsyncMock(return_value=None)
    yield saver


class TestDebateGraph:

    @pytest.mark.anyio
    async def test_run_returns_state_and_decision(self):
        settings = _mock_settings(max_rounds=2)
        graph = DebateGraph(llm_client=_mock_llm(), settings=settings)
        state = DebateState(user_query="Should we expand internationally in Q3?")
        state.current_round = 1
        state.termination_reason = "consensus_reached"
        decision = _final_decision(state)

        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(
            return_value={
                "debate_state": state,
                "final_decision": decision,
            }
        )

        with patch("app.orchestrator.debate_graph.AsyncSqliteSaver.from_conn_string", return_value=_fake_saver_context()):
            with patch.object(DebateGraph, "_build", return_value=compiled):
                final_state, final_decision = await graph.run(
                    "Should we expand internationally in Q3?",
                    max_rounds=2,
                )

        assert final_state.thread_id == state.thread_id
        assert final_decision.decision == "Proceed with phased expansion."

    @pytest.mark.anyio
    async def test_run_uses_thread_id_in_graph_config(self):
        settings = _mock_settings()
        graph = DebateGraph(llm_client=_mock_llm(), settings=settings)
        state = DebateState(user_query="Should we expand internationally in Q3?")
        state.current_round = 1
        decision = _final_decision(state)

        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(
            return_value={"debate_state": state, "final_decision": decision}
        )

        with patch("app.orchestrator.debate_graph.AsyncSqliteSaver.from_conn_string", return_value=_fake_saver_context()):
            with patch.object(DebateGraph, "_build", return_value=compiled):
                await graph.run(state.user_query, initial_state=state)

        _, kwargs = compiled.ainvoke.call_args
        assert kwargs["config"]["configurable"]["thread_id"] == state.thread_id

    @pytest.mark.anyio
    async def test_resume_calls_ainvoke_with_none(self):
        """resume() must pass None as input so LangGraph loads from checkpoint."""
        settings = _mock_settings()
        graph = DebateGraph(llm_client=_mock_llm(), settings=settings)
        state = DebateState(user_query="Should we expand internationally in Q3?")
        state.current_round = 2
        state.termination_reason = "consensus_reached"
        decision = _final_decision(state)

        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(
            return_value={"debate_state": state, "final_decision": decision}
        )

        with patch("app.orchestrator.debate_graph.AsyncSqliteSaver.from_conn_string", return_value=_fake_saver_with_checkpoint()):
            with patch.object(DebateGraph, "_build", return_value=compiled):
                final_state, final_decision = await graph.resume(state.thread_id)

        pos_args, kw_args = compiled.ainvoke.call_args
        assert pos_args[0] is None, "resume() must call ainvoke(None, ...) not ainvoke(initial_state, ...)"
        assert final_decision.decision == "Proceed with phased expansion."
        assert final_state.thread_id == state.thread_id

    @pytest.mark.anyio
    async def test_resume_raises_value_error_when_no_checkpoint(self):
        """resume() must raise ValueError when no checkpoint exists for the thread_id."""
        settings = _mock_settings()
        graph = DebateGraph(llm_client=_mock_llm(), settings=settings)

        with patch("app.orchestrator.debate_graph.AsyncSqliteSaver.from_conn_string", return_value=_fake_saver_no_checkpoint()):
            with pytest.raises(ValueError, match="No checkpoint found"):
                await graph.resume("nonexistent-thread-id")


class TestNodeFactories:

    @pytest.mark.anyio
    async def test_proposals_node_collects_outputs(self):
        emit = MagicMock()
        persist_state = AsyncMock()
        agents: dict[str, BaseAgent] = {
            "Analyst": MagicMock(spec=BaseAgent),
            "Risk": MagicMock(spec=BaseAgent),
        }
        agents["Analyst"].name = "Analyst"
        agents["Risk"].name = "Risk"
        agents["Analyst"].run = AsyncMock(return_value=_agent_response("Analyst"))
        agents["Risk"].run = AsyncMock(return_value=_agent_response("Risk"))

        node = make_proposals_node(agents, emit, persist_state)
        debate_state = DebateState(user_query="Should we expand internationally in Q3?")
        graph_state: DebateGraphState = {
            "debate_state": debate_state,
            "should_continue": True,
            "final_decision": None,
        }

        result = await node(graph_state)

        assert len(result["debate_state"].rounds[-1].agent_outputs) == 2
        persist_state.assert_awaited_once()

    @pytest.mark.anyio
    async def test_critiques_node_skips_self_critiques(self):
        emit = MagicMock()
        persist_state = AsyncMock()
        agents: dict[str, BaseAgent] = {
            "Analyst": MagicMock(spec=BaseAgent),
            "Risk": MagicMock(spec=BaseAgent),
        }
        for name, agent in agents.items():
            agent.name = name
            agent.critique = AsyncMock(
                side_effect=lambda state, target, critic=name: _critique_response(critic, target.agent_name)
            )

        node = make_critiques_node(agents, emit, persist_state)
        round_data = DebateRound(
            round_number=1,
            agent_outputs=[_agent_response("Analyst"), _agent_response("Risk")],
        )
        debate_state = DebateState(
            user_query="Should we expand internationally in Q3?",
            current_round=1,
            rounds=[round_data],
        )
        graph_state: DebateGraphState = {
            "debate_state": debate_state,
            "should_continue": True,
            "final_decision": None,
        }

        result = await node(graph_state)

        assert len(result["debate_state"].rounds[-1].critiques) == 2
        for critique in result["debate_state"].rounds[-1].critiques:
            assert critique.critic_agent != critique.target_agent

    @pytest.mark.anyio
    async def test_revisions_node_replaces_outputs_in_place(self):
        emit = MagicMock()
        persist_state = AsyncMock()
        agents: dict[str, BaseAgent] = {
            "Analyst": MagicMock(spec=BaseAgent),
            "Risk": MagicMock(spec=BaseAgent),
        }
        agents["Analyst"].name = "Analyst"
        agents["Risk"].name = "Risk"
        agents["Analyst"].revise = AsyncMock(return_value=_agent_response("Analyst", confidence=0.91))
        agents["Risk"].revise = AsyncMock(return_value=_agent_response("Risk", confidence=0.83))

        node = make_revisions_node(agents, emit, persist_state)
        round_data = DebateRound(
            round_number=1,
            agent_outputs=[_agent_response("Analyst"), _agent_response("Risk")],
            critiques=[
                _critique_response("Risk", "Analyst"),
                _critique_response("Analyst", "Risk"),
            ],
        )
        debate_state = DebateState(
            user_query="Should we expand internationally in Q3?",
            current_round=1,
            rounds=[round_data],
        )
        graph_state: DebateGraphState = {
            "debate_state": debate_state,
            "should_continue": True,
            "final_decision": None,
        }

        result = await node(graph_state)

        outputs = result["debate_state"].rounds[-1].agent_outputs
        assert outputs[0].confidence_score == pytest.approx(0.91)
        assert outputs[1].confidence_score == pytest.approx(0.83)

    @pytest.mark.anyio
    async def test_convergence_node_uses_semantic_consensus_when_enabled(self):
        emit = MagicMock()
        persist_state = AsyncMock()
        moderator = MagicMock()
        moderator.synthesize = AsyncMock(return_value=_synthesis(agreement_score=0.4, should_continue=True))
        settings = _mock_settings(semantic_enabled=True, consensus_threshold=0.8)

        round_data = DebateRound(
            round_number=1,
            agent_outputs=[_agent_response("Analyst"), _agent_response("Risk")],
        )
        debate_state = DebateState(
            user_query="Should we expand internationally in Q3?",
            current_round=1,
            rounds=[round_data],
        )
        graph_state: DebateGraphState = {
            "debate_state": debate_state,
            "should_continue": True,
            "final_decision": None,
        }

        with patch("app.orchestrator.nodes.SemanticConsensusEngine") as engine_cls:
            engine = engine_cls.return_value
            engine.compute_semantic_similarity.return_value = 0.88
            engine.compute_agreement_score.return_value = 0.86

            node = make_convergence_node(moderator, settings, emit, persist_state)
            result = await node(graph_state)

        assert result["debate_state"].agreement_score == pytest.approx(0.86)
        assert result["should_continue"] is False

    @pytest.mark.anyio
    async def test_finalize_node_returns_final_decision(self):
        emit = MagicMock()
        persist_state = AsyncMock()
        moderator = MagicMock()
        debate_state = DebateState(
            user_query="Should we expand internationally in Q3?",
            current_round=1,
            rounds=[DebateRound(round_number=1)],
            agreement_score=0.82,
            termination_reason="consensus_reached",
        )
        moderator.finalize = AsyncMock(return_value=_final_decision(debate_state))
        node = make_finalize_node(moderator, emit, persist_state)
        graph_state: DebateGraphState = {
            "debate_state": debate_state,
            "should_continue": False,
            "final_decision": None,
        }

        result = await node(graph_state)

        assert result["final_decision"].thread_id == debate_state.thread_id
        assert result["debate_state"].status == "converged"
