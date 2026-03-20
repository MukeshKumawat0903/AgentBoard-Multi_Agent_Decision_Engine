"""Tests for specialized agents using the structured-output LLM interface."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.ethics_agent import EthicsAgent
from app.agents.moderator_agent import FinalDecisionLLMOutput, ModeratorAgent, ModeratorSynthesis
from app.agents.risk_agent import RiskAgent
from app.agents.strategy_agent import StrategyAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.utils.exceptions import LLMResponseError


def _mock_llm(result: object | None = None, side_effect: Exception | None = None) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke_structured = AsyncMock(return_value=result)
    if side_effect is not None:
        llm.ainvoke_structured.side_effect = side_effect
    return llm


def _agent_output(**kwargs: Any) -> dict[str, Any]:
    base = {
        "position": "My position on this matter.",
        "reasoning": "Because the data supports it.",
        "assumptions": ["Stable market conditions"],
        "confidence_score": 0.8,
    }
    return {**base, **kwargs}


def _critique_output(**kwargs: Any) -> dict[str, Any]:
    base = {
        "critique_points": ["Missing key data points"],
        "severity": "medium",
        "suggested_revision": None,
        "confidence_score": 0.7,
    }
    return {**base, **kwargs}


def _synthesis_output(**kwargs: Any) -> ModeratorSynthesis:
    base = {
        "summary": "Agents broadly agree on direction.",
        "agreement_areas": ["Market opportunity is real"],
        "disagreement_areas": ["Timing of launch"],
        "agreement_score": 0.65,
        "should_continue": True,
        "next_round_focus": "Resolve launch timing.",
    }
    return ModeratorSynthesis(**{**base, **kwargs})


def _final_output(**kwargs: Any) -> FinalDecisionLLMOutput:
    base = {
        "decision": "Proceed with phased expansion.",
        "rationale_summary": "Strong consensus after 3 rounds.",
        "confidence_score": 0.85,
        "agreement_score": 0.87,
        "risk_flags": ["Currency volatility"],
        "alternatives": ["Delay to Q4"],
        "dissenting_opinions": [],
    }
    return FinalDecisionLLMOutput(**{**base, **kwargs})


def _make_state(with_rounds: bool = False) -> DebateState:
    state = DebateState(
        user_query="Should our company expand into the Asian market in Q3?",
        current_round=1,
    )
    if with_rounds:
        state.rounds.append(
            DebateRound(
                round_number=1,
                agent_outputs=[
                    AgentResponse(
                        agent_name="Analyst",
                        round_number=1,
                        position="Strong demand signals in SE Asia.",
                        reasoning="Market data.",
                        confidence_score=0.85,
                    ),
                    AgentResponse(
                        agent_name="Risk",
                        round_number=1,
                        position="Regulatory risk in 3 of 5 target markets.",
                        reasoning="Compliance research.",
                        confidence_score=0.78,
                    ),
                    AgentResponse(
                        agent_name="Strategy",
                        round_number=1,
                        position="Phased pilot: Singapore then Malaysia.",
                        reasoning="Lower risk entry.",
                        confidence_score=0.82,
                    ),
                ],
            )
        )
    return state


def _target(agent_name: str = "Strategy") -> AgentResponse:
    return AgentResponse(
        agent_name=agent_name,
        round_number=1,
        position="Expand aggressively into 5 markets at once.",
        reasoning="First-mover advantage.",
        confidence_score=0.9,
    )


def _critiques() -> list[CritiqueResponse]:
    return [
        CritiqueResponse(
            critic_agent="Risk",
            target_agent="Strategy",
            round_number=1,
            critique_points=["Expansion too fast, high operational risk"],
            severity="high",
            confidence_score=0.8,
        )
    ]


class TestAnalystAgent:
    def test_instantiation(self):
        agent = AnalystAgent(llm_client=_mock_llm())
        assert agent.name == "Analyst"
        assert "Do NOT propose a strategy" in agent.system_prompt

    @pytest.mark.anyio
    async def test_run_returns_agent_response(self):
        agent = AnalystAgent(llm_client=_mock_llm(result=type("X", (), _agent_output())()))
        result = await agent.run(_make_state())
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Analyst"

    @pytest.mark.anyio
    async def test_proposal_prompt_contains_query(self):
        llm = _mock_llm(result=type("X", (), _agent_output())())
        agent = AnalystAgent(llm_client=llm)
        state = _make_state()
        await agent.run(state)
        assert state.user_query in llm.ainvoke_structured.call_args.kwargs["user_prompt"]

    @pytest.mark.anyio
    async def test_critique_prompt_contains_target_name(self):
        llm = _mock_llm(result=type("Y", (), _critique_output())())
        agent = AnalystAgent(llm_client=llm)
        await agent.critique(_make_state(), _target("Risk"))
        assert "Risk" in llm.ainvoke_structured.call_args.kwargs["user_prompt"]

    @pytest.mark.anyio
    async def test_revision_prompt_includes_prior_round_text(self):
        llm = _mock_llm(result=type("X", (), _agent_output())())
        agent = AnalystAgent(llm_client=llm)
        state = _make_state(with_rounds=True)
        state.current_round = 2
        await agent.revise(state, _critiques())
        prompt = llm.ainvoke_structured.call_args.kwargs["user_prompt"]
        assert "Critiques received" in prompt


class TestRiskAgent:
    def test_instantiation(self):
        agent = RiskAgent(llm_client=_mock_llm())
        assert agent.name == "Risk"
        assert "adversarial" in agent.system_prompt.lower()

    @pytest.mark.anyio
    async def test_proposal_prompt_uses_analyst_context(self):
        llm = _mock_llm(result=type("X", (), _agent_output())())
        agent = RiskAgent(llm_client=llm)
        state = _make_state(with_rounds=True)
        state.current_round = 2
        await agent.run(state)
        assert "Analyst's findings" in llm.ainvoke_structured.call_args.kwargs["user_prompt"]

    @pytest.mark.anyio
    async def test_critique_prompt_challenges_confidence(self):
        llm = _mock_llm(result=type("Y", (), _critique_output())())
        agent = RiskAgent(llm_client=llm)
        await agent.critique(_make_state(), _target())
        prompt = llm.ainvoke_structured.call_args.kwargs["user_prompt"]
        assert "overly optimistic confidence" in prompt


class TestStrategyAgent:
    def test_instantiation(self):
        agent = StrategyAgent(llm_client=_mock_llm())
        assert agent.name == "Strategy"
        assert "alternatives" in agent.system_prompt.lower()

    @pytest.mark.anyio
    async def test_proposal_prompt_uses_analyst_and_risk_context(self):
        llm = _mock_llm(result=type("X", (), _agent_output())())
        agent = StrategyAgent(llm_client=llm)
        state = _make_state(with_rounds=True)
        state.current_round = 2
        await agent.run(state)
        prompt = llm.ainvoke_structured.call_args.kwargs["user_prompt"]
        assert "Analyst findings" in prompt
        assert "Risk assessment" in prompt

    @pytest.mark.anyio
    async def test_revision_prompt_includes_critic_agent_name(self):
        llm = _mock_llm(result=type("X", (), _agent_output())())
        agent = StrategyAgent(llm_client=llm)
        await agent.revise(_make_state(), _critiques())
        assert "From Risk" in llm.ainvoke_structured.call_args.kwargs["user_prompt"]


class TestEthicsAgent:
    def test_instantiation(self):
        agent = EthicsAgent(llm_client=_mock_llm())
        assert agent.name == "Ethics"
        assert "VETO" in agent.system_prompt

    @pytest.mark.anyio
    async def test_proposal_prompt_includes_strategy_when_available(self):
        llm = _mock_llm(result=type("X", (), _agent_output())())
        agent = EthicsAgent(llm_client=llm)
        state = _make_state(with_rounds=True)
        state.current_round = 2
        await agent.run(state)
        prompt = llm.ainvoke_structured.call_args.kwargs["user_prompt"]
        assert "Proposed strategy" in prompt

    @pytest.mark.anyio
    async def test_critique_prompt_mentions_stakeholders(self):
        llm = _mock_llm(result=type("Y", (), _critique_output())())
        agent = EthicsAgent(llm_client=llm)
        await agent.critique(_make_state(), _target())
        prompt = llm.ainvoke_structured.call_args.kwargs["user_prompt"]
        assert "stakeholders" in prompt.lower()


class TestModeratorAgent:
    def test_instantiation(self):
        agent = ModeratorAgent(llm_client=_mock_llm())
        assert agent.name == "Moderator"
        assert "neutral" in agent.role.lower()

    @pytest.mark.anyio
    async def test_synthesize_returns_moderator_synthesis(self):
        llm = _mock_llm(result=_synthesis_output())
        agent = ModeratorAgent(llm_client=llm)
        result = await agent.synthesize(_make_state(with_rounds=True))
        assert isinstance(result, ModeratorSynthesis)
        assert result.agreement_score == pytest.approx(0.65)

    @pytest.mark.anyio
    async def test_run_wraps_synthesis_as_agent_response(self):
        llm = _mock_llm(result=_synthesis_output())
        agent = ModeratorAgent(llm_client=llm)
        result = await agent.run(_make_state(with_rounds=True))
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Moderator"

    @pytest.mark.anyio
    async def test_finalize_returns_final_decision(self):
        llm = _mock_llm(result=_final_output())
        agent = ModeratorAgent(llm_client=llm)
        state = _make_state(with_rounds=True)
        state.current_round = 3
        state.agreement_score = 0.87
        state.termination_reason = "consensus_reached"
        result = await agent.finalize(state)
        assert isinstance(result, FinalDecision)
        assert result.thread_id == state.thread_id
        assert result.total_rounds == 3
        assert result.query == state.user_query

    @pytest.mark.anyio
    async def test_finalize_propagates_structured_output_error(self):
        agent = ModeratorAgent(llm_client=_mock_llm(side_effect=LLMResponseError("bad output")))
        with pytest.raises(LLMResponseError, match="bad output"):
            await agent.finalize(_make_state(with_rounds=True))
