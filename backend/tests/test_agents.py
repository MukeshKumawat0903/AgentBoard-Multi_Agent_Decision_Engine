"""
Tests for all 5 specialized debate agents (Phase 5).

Architecture under test:
  AnalystAgent / RiskAgent / StrategyAgent / EthicsAgent
    → each inherits BaseAgent; tests verify prompt-builder focus
      and that they produce correct schema types from run()/critique()/revise()

  ModeratorAgent
    → overrides run(); also has synthesize() and finalize()
    → has extra schema: ModeratorSynthesis

All LLM calls are mocked so no network traffic is made.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
import asyncio

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.risk_agent import RiskAgent
from app.agents.strategy_agent import StrategyAgent
from app.agents.ethics_agent import EthicsAgent
from app.agents.moderator_agent import ModeratorAgent, ModeratorSynthesis
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.utils.exceptions import LLMResponseError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_llm(return_value: dict) -> MagicMock:
    llm = MagicMock()
    llm.chat_json = AsyncMock(return_value=return_value)
    return llm


def _agent_response_dict(**kwargs: Any) -> dict:
    base: dict[str, Any] = {
        "position": "My position on this matter.",
        "reasoning": "Because the data supports it.",
        "assumptions": ["Stable market conditions"],
        "confidence_score": 0.8,
    }
    return {**base, **kwargs}


def _critique_dict(**kwargs: Any) -> dict:
    base: dict[str, Any] = {
        "critique_points": ["Missing key data points"],
        "severity": "medium",
        "confidence_score": 0.7,
    }
    return {**base, **kwargs}


def _synthesis_dict(**kwargs: Any) -> dict:
    base: dict[str, Any] = {
        "summary": "Agents broadly agree on direction.",
        "agreement_areas": ["Market opportunity is real"],
        "disagreement_areas": ["Timing of launch"],
        "agreement_score": 0.65,
        "should_continue": True,
        "next_round_focus": "Resolve launch timing.",
    }
    return {**base, **kwargs}


def _final_decision_dict(**kwargs: Any) -> dict:
    base: dict[str, Any] = {
        "decision": "Proceed with phased expansion.",
        "rationale_summary": "Strong consensus after 3 rounds.",
        "confidence_score": 0.85,
        "agreement_score": 0.87,
        "risk_flags": ["Currency volatility"],
        "alternatives": ["Delay to Q4"],
        "dissenting_opinions": [],
    }
    return {**base, **kwargs}


def _make_state(with_rounds: bool = False) -> DebateState:
    state = DebateState(
        user_query="Should our company expand into the Asian market in Q3?",
        current_round=1,
    )
    if with_rounds:
        analyst_out = AgentResponse(
            agent_name="Analyst", round_number=1,
            position="Strong demand signals in SE Asia.",
            reasoning="Market data.", confidence_score=0.85,
        )
        risk_out = AgentResponse(
            agent_name="Risk", round_number=1,
            position="Regulatory risk in 3 of 5 target markets.",
            reasoning="Compliance research.", confidence_score=0.78,
        )
        strategy_out = AgentResponse(
            agent_name="Strategy", round_number=1,
            position="Phased pilot: Singapore then Malaysia.",
            reasoning="Lower risk entry.", confidence_score=0.82,
        )
        r1 = DebateRound(
            round_number=1,
            agent_outputs=[analyst_out, risk_out, strategy_out],
        )
        state.rounds.append(r1)
    return state


def _make_target_response(agent_name: str = "Strategy") -> AgentResponse:
    return AgentResponse(
        agent_name=agent_name,
        round_number=1,
        position="Expand aggressively into 5 markets at once.",
        reasoning="First-mover advantage.",
        confidence_score=0.9,
    )


def _make_critiques() -> list[CritiqueResponse]:
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


# ---------------------------------------------------------------------------
# AnalystAgent
# ---------------------------------------------------------------------------

class TestAnalystAgent:

    def test_instantiation(self):
        a = AnalystAgent(llm_client=_mock_llm({}))
        assert a.name == "Analyst"
        assert "JSON" in a.system_prompt

    def test_system_prompt_forbids_strategy(self):
        a = AnalystAgent(llm_client=_mock_llm({}))
        assert "Strategy Agent" in a.system_prompt or "strategy" in a.system_prompt.lower()

    @pytest.mark.anyio
    async def test_run_returns_agent_response(self):
        a = AnalystAgent(llm_client=_mock_llm(_agent_response_dict()))
        result = await a.run(_make_state())
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Analyst"

    @pytest.mark.anyio
    async def test_proposal_prompt_contains_query(self):
        state = _make_state()
        a = AnalystAgent(llm_client=_mock_llm(_agent_response_dict()))
        await a.run(state)
        prompt = a.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert state.user_query in prompt

    @pytest.mark.anyio
    async def test_critique_returns_critique_response(self):
        a = AnalystAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response()
        result = await a.critique(_make_state(), target)
        assert isinstance(result, CritiqueResponse)
        assert result.critic_agent == "Analyst"
        assert result.target_agent == "Strategy"

    @pytest.mark.anyio
    async def test_critique_prompt_contains_target_name(self):
        state = _make_state()
        target = _make_target_response("Risk")
        a = AnalystAgent(llm_client=_mock_llm(_critique_dict()))
        await a.critique(state, target)
        prompt = a.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Risk" in prompt

    @pytest.mark.anyio
    async def test_revise_returns_agent_response(self):
        a = AnalystAgent(llm_client=_mock_llm(_agent_response_dict()))
        result = await a.revise(_make_state(), _make_critiques())
        assert isinstance(result, AgentResponse)

    @pytest.mark.anyio
    async def test_proposal_prompt_includes_prior_rounds(self):
        state = _make_state(with_rounds=True)
        state.current_round = 2
        a = AnalystAgent(llm_client=_mock_llm(_agent_response_dict()))
        await a.run(state)
        prompt = a.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Prior round summaries" in prompt


# ---------------------------------------------------------------------------
# RiskAgent
# ---------------------------------------------------------------------------

class TestRiskAgent:

    def test_instantiation(self):
        r = RiskAgent(llm_client=_mock_llm({}))
        assert r.name == "Risk"
        assert "JSON" in r.system_prompt

    def test_system_prompt_is_adversarial(self):
        r = RiskAgent(llm_client=_mock_llm({}))
        assert "adversarial" in r.system_prompt.lower() or "stress-test" in r.system_prompt.lower()

    @pytest.mark.anyio
    async def test_run_returns_agent_response(self):
        r = RiskAgent(llm_client=_mock_llm(_agent_response_dict()))
        result = await r.run(_make_state())
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Risk"

    @pytest.mark.anyio
    async def test_proposal_prompt_includes_analyst_context_when_available(self):
        state = _make_state(with_rounds=True)
        state.current_round = 2
        r = RiskAgent(llm_client=_mock_llm(_agent_response_dict()))
        await r.run(state)
        prompt = r.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Analyst" in prompt

    @pytest.mark.anyio
    async def test_critique_returns_critique_response(self):
        r = RiskAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response("Strategy")
        result = await r.critique(_make_state(), target)
        assert isinstance(result, CritiqueResponse)
        assert result.critic_agent == "Risk"

    @pytest.mark.anyio
    async def test_critique_prompt_challenges_confidence(self):
        r = RiskAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response()
        await r.critique(_make_state(), target)
        prompt = r.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "confidence" in prompt.lower() or "optimistic" in prompt.lower()

    @pytest.mark.anyio
    async def test_revise_returns_agent_response(self):
        r = RiskAgent(llm_client=_mock_llm(_agent_response_dict()))
        result = await r.revise(_make_state(), _make_critiques())
        assert isinstance(result, AgentResponse)


# ---------------------------------------------------------------------------
# StrategyAgent
# ---------------------------------------------------------------------------

class TestStrategyAgent:

    def test_instantiation(self):
        s = StrategyAgent(llm_client=_mock_llm({}))
        assert s.name == "Strategy"
        assert "JSON" in s.system_prompt

    def test_system_prompt_requires_alternatives(self):
        s = StrategyAgent(llm_client=_mock_llm({}))
        assert "2 alternative" in s.system_prompt or "alternatives" in s.system_prompt.lower()

    @pytest.mark.anyio
    async def test_run_returns_agent_response(self):
        s = StrategyAgent(llm_client=_mock_llm(_agent_response_dict()))
        result = await s.run(_make_state())
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Strategy"

    @pytest.mark.anyio
    async def test_proposal_prompt_uses_analyst_and_risk_context(self):
        state = _make_state(with_rounds=True)
        state.current_round = 2
        s = StrategyAgent(llm_client=_mock_llm(_agent_response_dict()))
        await s.run(state)
        prompt = s.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Analyst" in prompt
        assert "Risk" in prompt

    @pytest.mark.anyio
    async def test_critique_returns_critique_response(self):
        s = StrategyAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response("Analyst")
        result = await s.critique(_make_state(), target)
        assert isinstance(result, CritiqueResponse)
        assert result.critic_agent == "Strategy"

    @pytest.mark.anyio
    async def test_critique_prompt_checks_actionability(self):
        s = StrategyAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response()
        await s.critique(_make_state(), target)
        prompt = s.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "actionable" in prompt.lower()

    @pytest.mark.anyio
    async def test_revise_incorporates_critique_text(self):
        s = StrategyAgent(llm_client=_mock_llm(_agent_response_dict()))
        critiques = _make_critiques()
        await s.revise(_make_state(), critiques)
        prompt = s.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Risk" in prompt  # critic agent name present in prompt


# ---------------------------------------------------------------------------
# EthicsAgent
# ---------------------------------------------------------------------------

class TestEthicsAgent:

    def test_instantiation(self):
        e = EthicsAgent(llm_client=_mock_llm({}))
        assert e.name == "Ethics"
        assert "JSON" in e.system_prompt

    def test_system_prompt_mentions_veto(self):
        e = EthicsAgent(llm_client=_mock_llm({}))
        assert "VETO" in e.system_prompt or "veto" in e.system_prompt.lower()

    @pytest.mark.anyio
    async def test_run_returns_agent_response(self):
        e = EthicsAgent(llm_client=_mock_llm(_agent_response_dict()))
        result = await e.run(_make_state())
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Ethics"

    @pytest.mark.anyio
    async def test_proposal_prompt_includes_strategy_when_available(self):
        state = _make_state(with_rounds=True)
        state.current_round = 2
        e = EthicsAgent(llm_client=_mock_llm(_agent_response_dict()))
        await e.run(state)
        prompt = e.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Strategy" in prompt or "strategy" in prompt.lower()

    @pytest.mark.anyio
    async def test_critique_returns_critique_response(self):
        e = EthicsAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response("Strategy")
        result = await e.critique(_make_state(), target)
        assert isinstance(result, CritiqueResponse)
        assert result.critic_agent == "Ethics"

    @pytest.mark.anyio
    async def test_critique_prompt_mentions_stakeholders(self):
        e = EthicsAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response()
        await e.critique(_make_state(), target)
        prompt = e.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "stakeholder" in prompt.lower() or "ethical" in prompt.lower()

    @pytest.mark.anyio
    async def test_revise_mentions_veto_in_prompt(self):
        e = EthicsAgent(llm_client=_mock_llm(_agent_response_dict()))
        await e.revise(_make_state(), _make_critiques())
        prompt = e.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "VETO" in prompt or "veto" in prompt.lower()


# ---------------------------------------------------------------------------
# ModeratorAgent – ModeratorSynthesis schema
# ---------------------------------------------------------------------------

class TestModeratorSynthesis:

    def test_valid_construction(self):
        s = ModeratorSynthesis(
            summary="Agents broadly agree.",
            agreement_areas=["Market opportunity"],
            disagreement_areas=["Timing"],
            agreement_score=0.72,
            should_continue=True,
            next_round_focus="Resolve timing.",
        )
        assert s.agreement_score == 0.72
        assert s.should_continue is True

    def test_agreement_score_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ModeratorSynthesis(
                summary="x", agreement_areas=[], disagreement_areas=[],
                agreement_score=1.5, should_continue=False,
            )

    def test_next_round_focus_defaults_none(self):
        s = ModeratorSynthesis(
            summary="Done.", agreement_areas=[], disagreement_areas=[],
            agreement_score=0.9, should_continue=False,
        )
        assert s.next_round_focus is None

    def test_json_schema_export(self):
        schema = ModeratorSynthesis.model_json_schema()
        assert "agreement_score" in schema["properties"]
        assert "should_continue" in schema["properties"]


# ---------------------------------------------------------------------------
# ModeratorAgent – behaviour
# ---------------------------------------------------------------------------

class TestModeratorAgent:

    def test_instantiation(self):
        m = ModeratorAgent(llm_client=_mock_llm({}))
        assert m.name == "Moderator"
        assert "neutral" in m.system_prompt.lower() or "Neutral" in m.system_prompt

    # synthesize() -------------------------------------------------------

    @pytest.mark.anyio
    async def test_synthesize_returns_moderator_synthesis(self):
        m = ModeratorAgent(llm_client=_mock_llm(_synthesis_dict()))
        result = await m.synthesize(_make_state(with_rounds=True))
        assert isinstance(result, ModeratorSynthesis)
        assert 0.0 <= result.agreement_score <= 1.0

    @pytest.mark.anyio
    async def test_synthesize_prompt_contains_agent_outputs(self):
        state = _make_state(with_rounds=True)
        m = ModeratorAgent(llm_client=_mock_llm(_synthesis_dict()))
        await m.synthesize(state)
        prompt = m.llm_client.chat_json.call_args.kwargs["user_prompt"]
        assert "Analyst" in prompt or "Risk" in prompt

    @pytest.mark.anyio
    async def test_synthesize_raises_on_bad_dict(self):
        m = ModeratorAgent(llm_client=_mock_llm({"unexpected": "data"}))
        with pytest.raises(LLMResponseError, match="ModeratorSynthesis parse failed"):
            await m.synthesize(_make_state())

    # run() --------------------------------------------------------------

    @pytest.mark.anyio
    async def test_run_returns_agent_response_wrapping_synthesis(self):
        m = ModeratorAgent(llm_client=_mock_llm(_synthesis_dict()))
        result = await m.run(_make_state(with_rounds=True))
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "Moderator"
        assert result.confidence_score == pytest.approx(0.65)

    # finalize() ---------------------------------------------------------

    @pytest.mark.anyio
    async def test_finalize_returns_final_decision(self):
        state = _make_state(with_rounds=True)
        state.agreement_score = 0.87
        m = ModeratorAgent(llm_client=_mock_llm(_final_decision_dict()))
        result = await m.finalize(state)
        assert isinstance(result, FinalDecision)
        assert result.thread_id == state.thread_id

    @pytest.mark.anyio
    async def test_finalize_injects_thread_id_and_rounds(self):
        state = _make_state(with_rounds=True)
        state.current_round = 3
        state.agreement_score = 0.8
        m = ModeratorAgent(llm_client=_mock_llm(_final_decision_dict()))
        result = await m.finalize(state)
        assert result.thread_id == state.thread_id
        assert result.total_rounds == 3
        assert result.termination_reason == "consensus_reached"

    @pytest.mark.anyio
    async def test_finalize_termination_max_rounds_when_below_threshold(self):
        state = _make_state(with_rounds=True)
        state.agreement_score = 0.60  # below 0.75 threshold
        m = ModeratorAgent(llm_client=_mock_llm(_final_decision_dict()))
        result = await m.finalize(state)
        assert result.termination_reason == "max_rounds_reached"

    @pytest.mark.anyio
    async def test_finalize_restores_system_prompt_after_swap(self):
        """finalize() swaps to FINAL_DECISION prompt then restores original."""
        state = _make_state(with_rounds=True)
        state.agreement_score = 0.9
        m = ModeratorAgent(llm_client=_mock_llm(_final_decision_dict()))
        original = m.system_prompt
        await m.finalize(state)
        assert m.system_prompt == original  # restored

    @pytest.mark.anyio
    async def test_finalize_raises_on_bad_dict(self):
        state = _make_state(with_rounds=True)
        state.agreement_score = 0.9
        m = ModeratorAgent(llm_client=_mock_llm({"unexpected": "data"}))
        with pytest.raises(LLMResponseError, match="FinalDecision parse failed"):
            await m.finalize(state)

    # critique() / revise() fall back to base ----------------------------

    @pytest.mark.anyio
    async def test_critique_returns_critique_response(self):
        m = ModeratorAgent(llm_client=_mock_llm(_critique_dict()))
        target = _make_target_response("Strategy")
        result = await m.critique(_make_state(), target)
        assert isinstance(result, CritiqueResponse)
        assert result.critic_agent == "Moderator"


# ---------------------------------------------------------------------------
# Cross-agent error handling (Phase 10 – required coverage)
# ---------------------------------------------------------------------------

class TestAgentErrorHandling:
    """Ensures every specialised agent handles bad LLM output gracefully."""

    @pytest.mark.anyio
    async def test_agent_handles_invalid_llm_response(self):
        """Any agent that receives garbage JSON raises LLMResponseError."""
        for AgentCls in [AnalystAgent, RiskAgent, StrategyAgent, EthicsAgent]:
            agent = AgentCls(llm_client=_mock_llm({"garbage": "data"}))
            with pytest.raises(LLMResponseError):
                await agent.run(_make_state())

    @pytest.mark.anyio
    async def test_agent_handles_timeout(self):
        """An asyncio.TimeoutError from the LLM is propagated upward."""
        for AgentCls in [AnalystAgent, RiskAgent, StrategyAgent, EthicsAgent]:
            llm = MagicMock()
            llm.chat_json = AsyncMock(side_effect=asyncio.TimeoutError)
            agent = AgentCls(llm_client=llm)
            with pytest.raises(asyncio.TimeoutError):
                await agent.run(_make_state())

