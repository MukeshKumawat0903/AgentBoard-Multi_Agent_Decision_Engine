"""
The convergence gate decides whether a debate continues. The moderator's own
continue/stop recommendation is not presented as that decision, and moderator
LLM calls follow the same per-agent configuration and logging as other agents.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.moderator_agent import FinalDecisionLLMOutput, ModeratorAgent, ModeratorSynthesis
from app.orchestrator.lg_state import DebateGraphState
from app.orchestrator.nodes import make_convergence_node
from app.schemas.state import DebateRound, DebateState
from tests.test_orchestrator import _agent_response, _mock_settings, _synthesis


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_synthesis_event_does_not_carry_the_moderators_stop_call():
    moderator = MagicMock()
    # The moderator says "stop", but round 1 of a min-2-round debate must continue.
    moderator.synthesize = AsyncMock(return_value=_synthesis(agreement_score=0.95, should_continue=False))
    emit = MagicMock()
    debate_state = DebateState(
        user_query="Should we expand internationally in Q3?",
        current_round=1,
        max_rounds=3,
        min_rounds=2,
        rounds=[DebateRound(round_number=1, agent_outputs=[_agent_response("Analyst"), _agent_response("Risk")])],
    )
    graph_state: DebateGraphState = {"debate_state": debate_state, "should_continue": True, "final_decision": None}

    result = await make_convergence_node(moderator, _mock_settings(), emit, AsyncMock())(graph_state)

    assert result["should_continue"] is True
    synthesis_events = [call.args[1] for call in emit.call_args_list if call.args[0] == "synthesis"]
    assert len(synthesis_events) == 1
    assert "should_continue" not in synthesis_events[0]


def test_synthesis_prompt_leaves_the_stop_decision_to_the_gate():
    state = DebateState(user_query="Should we expand internationally in Q3?", current_round=1, max_rounds=3)
    prompt = ModeratorAgent._build_synthesis_prompt(state)
    assert "agreement_score >= 0.75" not in prompt
    assert "decided separately" in prompt


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["synthesize", "finalize"])
async def test_moderator_calls_use_its_configured_temperature_and_retries(action, caplog):
    llm = MagicMock()
    llm.provider, llm.model = "groq", "test-model"
    if action == "synthesize":
        llm.ainvoke_structured = AsyncMock(return_value=_synthesis())
    else:
        llm.ainvoke_structured = AsyncMock(return_value=FinalDecisionLLMOutput(
            decision="Proceed", rationale_summary="why", confidence_score=0.8, agreement_score=0.8,
        ))
    moderator = ModeratorAgent(llm_client=llm)
    moderator.temperature, moderator.max_retries = 0.9, 5
    state = DebateState(user_query="Should we expand internationally in Q3?", current_round=2, max_rounds=3)

    with caplog.at_level(logging.INFO):
        await getattr(moderator, action)(state)

    kwargs = llm.ainvoke_structured.call_args.kwargs
    assert (kwargs["temperature"], kwargs["max_retries"]) == (0.9, 5)
    starts = [r for r in caplog.records if r.getMessage() == "llm_call_start"]
    assert [(r.agent, r.action, r.round) for r in starts] == [("Moderator", action, 2)]


def test_moderator_fields_are_described_as_advisory():
    fields = ModeratorSynthesis.model_fields
    assert "gate" in (fields["should_continue"].description or "")
    assert "gate" in (fields["agreement_score"].description or "")
