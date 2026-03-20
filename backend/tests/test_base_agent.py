"""Tests for the structured-output BaseAgent implementation."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base_agent import AgentLLMOutput, BaseAgent, CritiqueLLMOutput
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.utils.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError

_SYSTEM_PROMPT = "You are a test agent."


def _make_state(**kwargs: Any) -> DebateState:
    defaults: dict[str, Any] = {
        "user_query": "Should we expand internationally in Q3?",
        "current_round": 1,
    }
    return DebateState(**(defaults | kwargs))


def _make_agent_output(**kwargs: Any) -> AgentLLMOutput:
    defaults = {
        "position": "Option A is best.",
        "reasoning": "Strong cost savings.",
        "assumptions": ["Stable market"],
        "confidence_score": 0.8,
    }
    return AgentLLMOutput(**(defaults | kwargs))


def _make_critique_output(**kwargs: Any) -> CritiqueLLMOutput:
    defaults = {
        "critique_points": ["Overlooks regulatory risk"],
        "severity": "medium",
        "suggested_revision": None,
        "confidence_score": 0.7,
    }
    return CritiqueLLMOutput(**(defaults | kwargs))


def _make_mock_llm(result: object | None = None, side_effect: Exception | None = None) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke_structured = AsyncMock(return_value=result)
    if side_effect is not None:
        llm.ainvoke_structured.side_effect = side_effect
    return llm


class EchoAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(
            name="Echo",
            role="tester",
            system_prompt=_SYSTEM_PROMPT,
            llm_client=llm_client,
        )
        self.last_proposal_state: DebateState | None = None
        self.last_critique_target: AgentResponse | None = None
        self.last_revision_critiques: list[CritiqueResponse] | None = None

    def _build_proposal_prompt(self, state: DebateState) -> str:
        self.last_proposal_state = state
        return f"Proposal for: {state.user_query}"

    def _build_critique_prompt(self, state: DebateState, target: AgentResponse) -> str:
        self.last_critique_target = target
        return f"Critique {target.agent_name} round {state.current_round}"

    def _build_revision_prompt(self, state: DebateState, critiques: list[CritiqueResponse]) -> str:
        self.last_revision_critiques = critiques
        return f"Revise based on {len(critiques)} critiques"


def test_base_agent_cannot_be_instantiated_directly():
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BaseAgent(name="X", role="x", system_prompt="x", llm_client=MagicMock())  # type: ignore[abstract]


def test_subclass_missing_abstract_method_cannot_be_instantiated():
    class Incomplete(BaseAgent):
        def _build_proposal_prompt(self, state: DebateState) -> str:
            return ""

        def _build_critique_prompt(self, state: DebateState, target: AgentResponse) -> str:
            return ""

    with pytest.raises(TypeError):
        Incomplete(name="X", role="x", system_prompt="x", llm_client=MagicMock())  # type: ignore[abstract]


@pytest.mark.anyio
async def test_run_calls_structured_llm_with_agent_schema():
    state = _make_state()
    llm = _make_mock_llm(_make_agent_output())
    agent = EchoAgent(llm_client=llm)

    result = await agent.run(state)

    assert agent.last_proposal_state is state
    assert isinstance(result, AgentResponse)
    call = llm.ainvoke_structured.call_args
    assert call.args[0] is AgentLLMOutput
    assert call.kwargs["system_prompt"] == _SYSTEM_PROMPT
    assert "Proposal for:" in call.kwargs["user_prompt"]


@pytest.mark.anyio
async def test_run_returns_agent_response():
    agent = EchoAgent(llm_client=_make_mock_llm(_make_agent_output(confidence_score=0.82)))

    result = await agent.run(_make_state(current_round=3))

    assert result.agent_name == "Echo"
    assert result.round_number == 3
    assert result.confidence_score == pytest.approx(0.82)


@pytest.mark.anyio
async def test_critique_calls_structured_llm_with_critique_schema():
    llm = _make_mock_llm(_make_critique_output())
    agent = EchoAgent(llm_client=llm)
    state = _make_state(current_round=2)
    target = AgentResponse(
        agent_name="Analyst",
        round_number=2,
        position="Option A.",
        reasoning="Data.",
        confidence_score=0.9,
    )

    result = await agent.critique(state, target)

    assert agent.last_critique_target is target
    assert result.critic_agent == "Echo"
    assert result.target_agent == "Analyst"
    assert result.round_number == 2
    call = llm.ainvoke_structured.call_args
    assert call.args[0] is CritiqueLLMOutput
    assert "Critique Analyst round 2" in call.kwargs["user_prompt"]


@pytest.mark.anyio
async def test_revise_returns_agent_response():
    critiques = [
        CritiqueResponse(
            critic_agent="Risk",
            target_agent="Echo",
            round_number=1,
            critique_points=["Too optimistic"],
            severity="medium",
            confidence_score=0.7,
        )
    ]
    llm = _make_mock_llm(_make_agent_output(position="Revised position."))
    agent = EchoAgent(llm_client=llm)

    result = await agent.revise(_make_state(), critiques)

    assert agent.last_revision_critiques is critiques
    assert result.position == "Revised position."


@pytest.mark.anyio
async def test_run_propagates_llm_response_error():
    agent = EchoAgent(llm_client=_make_mock_llm(side_effect=LLMResponseError("invalid output")))

    with pytest.raises(LLMResponseError, match="invalid output"):
        await agent.run(_make_state())


@pytest.mark.anyio
async def test_run_propagates_connection_error():
    agent = EchoAgent(llm_client=_make_mock_llm(side_effect=LLMConnectionError("network down")))

    with pytest.raises(LLMConnectionError):
        await agent.run(_make_state())


@pytest.mark.anyio
async def test_run_propagates_rate_limit_error():
    agent = EchoAgent(llm_client=_make_mock_llm(side_effect=LLMRateLimitError("rate limited")))

    with pytest.raises(LLMRateLimitError):
        await agent.run(_make_state())


@pytest.mark.anyio
async def test_run_emits_log_records(caplog: pytest.LogCaptureFixture):
    import logging

    agent = EchoAgent(llm_client=_make_mock_llm(_make_agent_output()))

    with caplog.at_level(logging.INFO, logger="agentboard.agents.echo"):
        await agent.run(_make_state())

    messages = [record.message for record in caplog.records]
    assert "llm_call_start" in messages
    assert "llm_call_done" in messages


def test_repr_contains_name_and_role():
    agent = EchoAgent(llm_client=MagicMock())
    rendered = repr(agent)
    assert "EchoAgent" in rendered
    assert "Echo" in rendered
    assert "tester" in rendered
