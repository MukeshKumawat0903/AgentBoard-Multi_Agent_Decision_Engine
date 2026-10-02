"""Stance-based agreement: the structured verdict each agent declares, and how
the convergence node turns it into the agreement score."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import AgentLLMOutput
from app.agents.ethics_agent import EthicsAgent, EthicsLLMOutput
from app.agents.risk_agent import RiskAgent
from app.schemas.agent_response import AgentResponse
from app.schemas.state import DebateState

QUERY = "Should we expand into Southeast Asia next year?"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _llm(result) -> MagicMock:
    llm = MagicMock()
    llm.provider, llm.model = "groq", "test-model"
    llm.ainvoke_structured = AsyncMock(return_value=result)
    return llm


# --- schema + agent plumbing -------------------------------------------------

def test_stance_is_required_in_the_llm_schema():
    assert "stance" in AgentLLMOutput.model_json_schema()["required"]
    assert "stance" in EthicsLLMOutput.model_json_schema()["required"]


def test_stance_is_optional_on_stored_responses():
    assert "stance" not in AgentResponse.model_json_schema().get("required", [])


def test_a_debate_stored_before_stance_existed_still_loads():
    legacy = {
        "user_query": QUERY,
        "current_round": 1,
        "rounds": [{
            "round_number": 1,
            "agent_outputs": [{
                "agent_name": "Risk", "round_number": 1, "position": "Too risky.",
                "reasoning": "r", "confidence_score": 0.7,
            }],
        }],
    }
    state = DebateState.model_validate(legacy)
    assert state.rounds[0].agent_outputs[0].stance is None


@pytest.mark.anyio
async def test_stance_is_mapped_onto_the_response():
    llm = _llm(AgentLLMOutput(position="Too risky.", reasoning="r", confidence_score=0.7, stance="oppose"))
    response = await RiskAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=1))
    assert response.stance == "oppose"


@pytest.mark.anyio
@pytest.mark.parametrize("stance", ["support", "conditional"])
async def test_a_veto_coerces_a_supporting_stance_to_oppose(stance):
    llm = _llm(EthicsLLMOutput(
        position="Breaches consent.", reasoning="r", confidence_score=0.9,
        stance=stance, veto=True, veto_reason="No consent.",
    ))
    response = await EthicsAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=1))
    assert (response.veto, response.stance) == (True, "oppose")


@pytest.mark.anyio
async def test_without_a_veto_the_stance_is_kept():
    llm = _llm(EthicsLLMOutput(
        position="Fine with safeguards.", reasoning="r", confidence_score=0.8, stance="conditional",
    ))
    response = await EthicsAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=1))
    assert response.stance == "conditional"


@pytest.mark.anyio
async def test_prompts_ask_for_a_stance_with_role_guidance():
    output = AgentLLMOutput(position="Facts.", reasoning="r", confidence_score=0.7, stance="abstain")
    analyst_llm, risk_llm = _llm(output), _llm(output)
    state = DebateState(user_query=QUERY, current_round=1)

    await AnalystAgent(llm_client=analyst_llm).run(state)
    await RiskAgent(llm_client=risk_llm).revise(state, [])

    analyst_prompt = analyst_llm.ainvoke_structured.call_args.kwargs["user_prompt"]
    risk_prompt = risk_llm.ainvoke_structured.call_args.kwargs["user_prompt"]
    assert "Set `stance`" in analyst_prompt and "set stance to `abstain`" in analyst_prompt
    assert "Set `stance`" in risk_prompt and "set stance to `abstain`" not in risk_prompt


@pytest.mark.anyio
async def test_ethics_prompt_ties_veto_to_oppose():
    llm = _llm(EthicsLLMOutput(position="ok", reasoning="r", confidence_score=0.8, stance="support"))
    await EthicsAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=1))
    assert "If you set veto=true, your stance must be `oppose`." in llm.ainvoke_structured.call_args.kwargs["user_prompt"]
