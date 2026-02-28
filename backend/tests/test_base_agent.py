"""
Tests for BaseAgent (app/agents/base_agent.py).

Uses a minimal concrete subclass (EchoAgent) so the abstract class can be
instantiated and exercised without any real agent implementation.

Covers:
- Cannot instantiate BaseAgent directly
- Subclass missing any abstract method raises TypeError
- run() / critique() / revise() call the right prompt builders and parse correctly
- _parse_response injects agent_name + round_number defaults
- _parse_critique injects critic_agent + target_agent + round_number defaults
- Invalid raw dict raises LLMResponseError
- Logging calls are emitted
- __repr__ format
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateRound, DebateState
from app.utils.exceptions import LLMResponseError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = "You are a test agent. Output JSON only."


def _make_state(**kwargs: Any) -> DebateState:
    defaults: dict[str, Any] = {
        "user_query": "Should we expand internationally in Q3?",
        "current_round": 1,
    }
    return DebateState(**(defaults | kwargs))


def _make_agent_response_dict(**kwargs: Any) -> dict:
    defaults: dict[str, Any] = {
        "position": "Option A is best.",
        "reasoning": "Strong cost savings.",
        "assumptions": ["Market is stable"],
        "confidence_score": 0.8,
    }
    return {**defaults, **kwargs}


def _make_critique_dict(**kwargs: Any) -> dict:
    defaults: dict[str, Any] = {
        "critique_points": ["Overlooks regulatory risk"],
        "severity": "medium",
        "confidence_score": 0.7,
    }
    return {**defaults, **kwargs}


def _make_mock_llm(return_value: dict) -> MagicMock:
    llm = MagicMock()
    llm.chat_json = AsyncMock(return_value=return_value)
    return llm


# ---------------------------------------------------------------------------
# EchoAgent – minimal concrete subclass used for all tests
# ---------------------------------------------------------------------------

class EchoAgent(BaseAgent):
    """Concrete agent that records which prompts it built."""

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

    def _build_revision_prompt(
        self, state: DebateState, critiques: list[CritiqueResponse]
    ) -> str:
        self.last_revision_critiques = critiques
        return f"Revise based on {len(critiques)} critiques"


# ---------------------------------------------------------------------------
# 1. Instantiation guards
# ---------------------------------------------------------------------------


def test_base_agent_cannot_be_instantiated_directly():
    """BaseAgent is abstract; direct instantiation must raise TypeError."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BaseAgent(  # type: ignore[abstract]
            name="X", role="x", system_prompt="x", llm_client=MagicMock()
        )


def test_subclass_missing_one_abstract_method_cannot_be_instantiated():
    """A subclass that omits even one abstract method must raise TypeError."""

    class Incomplete(BaseAgent):
        def _build_proposal_prompt(self, state: DebateState) -> str:
            return ""

        def _build_critique_prompt(
            self, state: DebateState, target: AgentResponse
        ) -> str:
            return ""

        # _build_revision_prompt deliberately omitted

    with pytest.raises(TypeError):
        Incomplete(name="X", role="x", system_prompt="x", llm_client=MagicMock())  # type: ignore[abstract]


def test_concrete_subclass_can_be_instantiated():
    agent = EchoAgent(llm_client=_make_mock_llm({}))
    assert agent.name == "Echo"
    assert agent.role == "tester"


# ---------------------------------------------------------------------------
# 2. run()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_calls_proposal_prompt_builder():
    state = _make_state()
    llm = _make_mock_llm(_make_agent_response_dict())
    agent = EchoAgent(llm_client=llm)

    await agent.run(state)

    assert agent.last_proposal_state is state


@pytest.mark.anyio
async def test_run_calls_chat_json():
    state = _make_state()
    llm = _make_mock_llm(_make_agent_response_dict())
    agent = EchoAgent(llm_client=llm)

    await agent.run(state)

    llm.chat_json.assert_called_once()
    call_kwargs = llm.chat_json.call_args
    assert call_kwargs.kwargs["system_prompt"] == _SYSTEM_PROMPT
    assert "Proposal for:" in call_kwargs.kwargs["user_prompt"]


@pytest.mark.anyio
async def test_run_returns_agent_response():
    state = _make_state()
    llm = _make_mock_llm(_make_agent_response_dict())
    agent = EchoAgent(llm_client=llm)

    result = await agent.run(state)

    assert isinstance(result, AgentResponse)
    assert result.agent_name == "Echo"
    assert result.round_number == 1
    assert result.confidence_score == 0.8


@pytest.mark.anyio
async def test_run_injects_agent_name_and_round_number():
    """LLM response that omits agent_name/round_number gets them injected."""
    state = _make_state(current_round=3)
    raw = _make_agent_response_dict()  # no agent_name / round_number
    raw.pop("agent_name", None)
    raw.pop("round_number", None)
    llm = _make_mock_llm(raw)
    agent = EchoAgent(llm_client=llm)

    result = await agent.run(state)

    assert result.agent_name == "Echo"
    assert result.round_number == 3


# ---------------------------------------------------------------------------
# 3. critique()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_critique_calls_critique_prompt_builder():
    state = _make_state()
    target = AgentResponse(
        agent_name="Analyst",
        round_number=1,
        position="Option A.",
        reasoning="Data.",
        confidence_score=0.9,
    )
    llm = _make_mock_llm(_make_critique_dict())
    agent = EchoAgent(llm_client=llm)

    await agent.critique(state, target)

    assert agent.last_critique_target is target


@pytest.mark.anyio
async def test_critique_returns_critique_response():
    state = _make_state()
    target = AgentResponse(
        agent_name="Strategy",
        round_number=1,
        position="Expand now.",
        reasoning="Big upside.",
        confidence_score=0.75,
    )
    llm = _make_mock_llm(_make_critique_dict())
    agent = EchoAgent(llm_client=llm)

    result = await agent.critique(state, target)

    assert isinstance(result, CritiqueResponse)
    assert result.critic_agent == "Echo"
    assert result.target_agent == "Strategy"
    assert result.round_number == 1


@pytest.mark.anyio
async def test_critique_injects_critic_target_round():
    """Critique dict that omits all context fields gets them injected."""
    state = _make_state(current_round=2)
    target = AgentResponse(
        agent_name="Risk",
        round_number=2,
        position="Too risky.",
        reasoning="Volatility.",
        confidence_score=0.6,
    )
    raw = _make_critique_dict()
    # explicitly remove context fields
    raw.pop("critic_agent", None)
    raw.pop("target_agent", None)
    raw.pop("round_number", None)
    llm = _make_mock_llm(raw)
    agent = EchoAgent(llm_client=llm)

    result = await agent.critique(state, target)

    assert result.critic_agent == "Echo"
    assert result.target_agent == "Risk"
    assert result.round_number == 2


# ---------------------------------------------------------------------------
# 4. revise()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_revise_calls_revision_prompt_builder():
    state = _make_state()
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
    llm = _make_mock_llm(_make_agent_response_dict())
    agent = EchoAgent(llm_client=llm)

    await agent.revise(state, critiques)

    assert agent.last_revision_critiques is critiques


@pytest.mark.anyio
async def test_revise_returns_agent_response():
    state = _make_state()
    critiques: list[CritiqueResponse] = []
    llm = _make_mock_llm(_make_agent_response_dict())
    agent = EchoAgent(llm_client=llm)

    result = await agent.revise(state, critiques)

    assert isinstance(result, AgentResponse)
    assert result.agent_name == "Echo"


# ---------------------------------------------------------------------------
# 5. _parse_response error case
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_raises_llm_response_error_on_bad_dict():
    """If LLM returns a dict missing required fields, raise LLMResponseError."""
    state = _make_state()
    bad_raw = {"unexpected_key": "no_schema_match"}
    llm = _make_mock_llm(bad_raw)
    agent = EchoAgent(llm_client=llm)

    with pytest.raises(LLMResponseError, match="AgentResponse parse failed"):
        await agent.run(state)


# ---------------------------------------------------------------------------
# 6. _parse_critique error case
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_critique_raises_llm_response_error_on_bad_dict():
    """If LLM returns a dict missing required critique fields, raise LLMResponseError."""
    state = _make_state()
    target = AgentResponse(
        agent_name="Analyst",
        round_number=1,
        position="P.",
        reasoning="R.",
        confidence_score=0.5,
    )
    bad_raw: dict[str, Any] = {"unexpected": "data"}
    llm = _make_mock_llm(bad_raw)
    agent = EchoAgent(llm_client=llm)

    with pytest.raises(LLMResponseError, match="CritiqueResponse parse failed"):
        await agent.critique(state, target)


# ---------------------------------------------------------------------------
# 7. LLM exceptions propagate unchanged
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_propagates_llm_connection_error():
    from app.utils.exceptions import LLMConnectionError

    state = _make_state()
    llm = MagicMock()
    llm.chat_json = AsyncMock(side_effect=LLMConnectionError("network down"))
    agent = EchoAgent(llm_client=llm)

    with pytest.raises(LLMConnectionError):
        await agent.run(state)


@pytest.mark.anyio
async def test_run_propagates_llm_rate_limit_error():
    from app.utils.exceptions import LLMRateLimitError

    state = _make_state()
    llm = MagicMock()
    llm.chat_json = AsyncMock(side_effect=LLMRateLimitError("rate limited"))
    agent = EchoAgent(llm_client=llm)

    with pytest.raises(LLMRateLimitError):
        await agent.run(state)


# ---------------------------------------------------------------------------
# 8. Logging
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_emits_log_records(caplog: pytest.LogCaptureFixture):
    import logging

    state = _make_state()
    llm = _make_mock_llm(_make_agent_response_dict())
    agent = EchoAgent(llm_client=llm)

    with caplog.at_level(logging.DEBUG, logger="agentboard.agents.echo"):
        await agent.run(state)

    messages = [r.message for r in caplog.records]
    assert any("llm_call_start" in m for m in messages)
    assert any("llm_call_done" in m for m in messages)


# ---------------------------------------------------------------------------
# 9. __repr__
# ---------------------------------------------------------------------------


def test_repr_contains_name_and_role():
    agent = EchoAgent(llm_client=MagicMock())
    r = repr(agent)
    assert "EchoAgent" in r
    assert "Echo" in r
    assert "tester" in r
