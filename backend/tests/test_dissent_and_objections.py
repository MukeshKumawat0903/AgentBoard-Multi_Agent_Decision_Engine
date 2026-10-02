"""Rule 3 (dissent) and Rule 4 (open objections) of the consensus gate.

Rule 3: a dissenter is a voting agent whose stance differs from the majority,
shared by the gate and the minority report.
Rule 4: a high/critical critique stays open until the target's revision
addresses it (a rebuttal is enough for high, not for critical).
"""

from __future__ import annotations

import itertools
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import CRITIQUE_REPLY_INSTRUCTION, AgentLLMOutput
from app.agents.domain_agents import FinancialEthicsAgent, SecurityAgent
from app.agents.ethics_agent import EthicsAgent, EthicsLLMOutput
from app.agents.risk_agent import RiskAgent
from app.agents.strategy_agent import StrategyAgent
from app.orchestrator.nodes import make_convergence_node, make_finalize_node
from app.schemas.agent_response import AgentResponse, CritiqueReply, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.services.consensus import (
    ConsensusSignals,
    _confidence_gap_dissenters,
    compute_stance_agreement,
    count_dissenting_agents,
    is_consensus_reached,
    majority_stance,
    select_dissenting_agents,
    stance_weights,
)
from tests.test_orchestrator import _mock_settings, _synthesis

QUERY = "Should we expand into Southeast Asia next year?"
BAND = 0.20


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _agent(name: str, stance: str | None, confidence: float, round_number: int = 2) -> AgentResponse:
    # Identical wording so Rule 1 (lexical fallback) and drift don't get in the way.
    return AgentResponse(
        agent_name=name, round_number=round_number,
        position="We should decide on the Southeast Asia expansion next year.",
        reasoning="r", confidence_score=confidence, stance=stance,
    )


def _names(responses: list[AgentResponse]) -> list[str]:
    return [r.agent_name for r in responses]


# --- who is a dissenter -------------------------------------------------------

def test_a_confident_opponent_dissents_and_an_unsure_ally_does_not():
    responses = [
        _agent("Strategy", "support", 0.85),
        _agent("Risk", "oppose", 0.90),
        _agent("Ethics", "support", 0.50),
    ]
    assert _names(select_dissenting_agents(responses, BAND)) == ["Risk"]
    # The old confidence-gap rule got this backwards.
    assert _names(_confidence_gap_dissenters(responses, BAND)) == ["Ethics"]


def test_unanimous_voters_have_no_dissenters_whatever_their_confidence():
    responses = [_agent(n, "support", c) for n, c in zip("ABCD", (0.9, 0.9, 0.9, 0.5))]
    assert select_dissenting_agents(responses, BAND) == []


def test_abstainers_never_dissent():
    responses = [_agent("Analyst", "abstain", 0.2)] + [_agent(n, "support", 0.9) for n in ("Risk", "Strategy", "Ethics")]
    assert select_dissenting_agents(responses, BAND) == []


def test_agents_without_a_stance_never_dissent_once_others_vote():
    responses = [_agent("Legacy", None, 0.1), _agent("Risk", "support", 0.9), _agent("Strategy", "oppose", 0.4)]
    assert _names(select_dissenting_agents(responses, BAND)) == ["Strategy"]


def test_rule_three_catches_overruled_agents_that_rule_one_lets_through():
    responses = [
        _agent("Strategy", "support", 0.9), _agent("Finance", "support", 0.9),
        _agent("Risk", "oppose", 0.2), _agent("Ethics", "conditional", 0.2),
    ]
    assert compute_stance_agreement(responses) == pytest.approx(1.8 / 2.2)  # 0.82 passes Standard
    assert count_dissenting_agents(responses, BAND) == 2
    signals = ConsensusSignals(
        position_agreement=compute_stance_agreement(responses) or 0.0,
        rounds_completed=2,
        dissenting_agents=count_dissenting_agents(responses, BAND),
        open_disagreements=0,
        confidence_converged=True,
    )
    assert not is_consensus_reached(
        signals, threshold=0.75, min_rounds=2, max_dissent=1, max_open_disagreements=2,
    )


def test_fewer_than_two_voters_fall_back_to_the_confidence_gap():
    responses = [_agent("A", None, 0.9), _agent("B", None, 0.9), _agent("C", "support", 0.4)]
    assert majority_stance(responses) is None
    assert _names(select_dissenting_agents(responses, BAND)) == ["C"]


def test_the_fallback_on_an_empty_round_is_empty():
    assert select_dissenting_agents([], BAND) == []


# --- majority and tie-breaks --------------------------------------------------

def test_stance_weights_sum_confidence_per_voting_stance():
    responses = [_agent("A", "support", 0.8), _agent("B", "support", 0.6), _agent("C", "abstain", 0.9)]
    voters, weights = stance_weights(responses)
    assert _names(voters) == ["A", "B"]
    assert dict(weights) == {"support": pytest.approx(1.4)}


def test_majority_is_the_largest_summed_confidence_not_the_head_count():
    responses = [_agent("A", "support", 0.3), _agent("B", "support", 0.3), _agent("C", "oppose", 0.9)]
    assert majority_stance(responses) == "oppose"


def test_equal_weight_goes_to_the_larger_group():
    responses = [_agent("A", "support", 0.5), _agent("B", "support", 0.5), _agent("C", "oppose", 1.0)]
    assert majority_stance(responses) == "support"


def test_float_noise_does_not_break_a_tie():
    # 0.1 + 0.2 != 0.3 in floating point; the head count must still decide.
    responses = [_agent("A", "support", 0.1), _agent("B", "support", 0.2), _agent("C", "oppose", 0.3)]
    assert majority_stance(responses) == "support"


def test_an_exact_tie_resolves_the_same_way_in_any_order():
    responses = [
        _agent("Risk", "oppose", 0.8), _agent("Strategy", "support", 0.8),
        _agent("Ethics", "oppose", 0.8), _agent("Finance", "support", 0.8),
    ]
    results = {
        (majority_stance(list(order)), tuple(sorted(_names(select_dissenting_agents(list(order), BAND)))))
        for order in itertools.permutations(responses)
    }
    assert results == {("oppose", ("Finance", "Strategy"))}


# --- convergence gate ---------------------------------------------------------

def _two_round_state(outputs: list[AgentResponse]) -> DebateState:
    # Same positions in both rounds → drift 0, so Rule 5 passes and Rule 3 decides.
    previous = [o.model_copy(update={"round_number": 1}) for o in outputs]
    return DebateState(
        user_query=QUERY, current_round=2, max_rounds=4, min_rounds=2,
        rounds=[DebateRound(round_number=1, agent_outputs=previous),
                DebateRound(round_number=2, agent_outputs=outputs)],
    )


async def _converge(ds: DebateState) -> dict:
    moderator = MagicMock()
    moderator.synthesize = AsyncMock(return_value=_synthesis(agreement_score=0.9, should_continue=False))
    settings = _mock_settings()
    settings.AGREEMENT_METHOD = "stance"
    node = make_convergence_node(moderator, settings, MagicMock(), AsyncMock())
    return await node({"debate_state": ds, "should_continue": True, "final_decision": None})


@pytest.mark.anyio
async def test_two_overruled_agents_block_consensus():
    outputs = [
        _agent("Strategy", "support", 0.9), _agent("Finance", "support", 0.9),
        _agent("Risk", "oppose", 0.2), _agent("Ethics", "conditional", 0.2),
    ]
    result = await _converge(_two_round_state(outputs))
    assert result["should_continue"] is True
    assert result["debate_state"].termination_reason != "consensus_reached"


@pytest.mark.anyio
async def test_one_overruled_agent_is_tolerated():
    outputs = [
        _agent("Strategy", "support", 0.9), _agent("Finance", "support", 0.9),
        _agent("Ethics", "support", 0.9), _agent("Risk", "oppose", 0.2),
    ]
    result = await _converge(_two_round_state(outputs))
    assert result["debate_state"].termination_reason == "consensus_reached"


# --- minority report ----------------------------------------------------------

async def _finalize(final_outputs: list[AgentResponse]) -> FinalDecision:
    ds = DebateState(
        user_query=QUERY, current_round=2, termination_reason="max_rounds_reached",
        rounds=[DebateRound(round_number=1), DebateRound(round_number=2, agent_outputs=final_outputs)],
    )
    moderator = MagicMock()
    moderator.finalize = AsyncMock(return_value=FinalDecision(
        thread_id=ds.thread_id, decision="d", rationale_summary="r", confidence_score=0.8,
        agreement_score=0.5, total_rounds=2, termination_reason="max_rounds_reached",
    ))
    node = make_finalize_node(moderator, MagicMock(), settings=_mock_settings())
    result = await node({"debate_state": ds, "should_continue": False, "final_decision": None})
    return result["final_decision"]


@pytest.mark.anyio
async def test_minority_report_names_the_gate_dissenters_with_stance_wording():
    outputs = [
        _agent("Analyst", "abstain", 0.3),
        _agent("Strategy", "support", 0.85),
        _agent("Risk", "oppose", 0.90),
        _agent("Ethics", "support", 0.50),
    ]
    decision = await _finalize(outputs)

    assert [e.agent_name for e in decision.minority_report] == _names(select_dissenting_agents(outputs, BAND))
    assert decision.minority_report[0].dissent_reason == "Voted oppose while the majority voted support."


@pytest.mark.anyio
async def test_minority_report_keeps_the_confidence_gap_wording_without_stances():
    outputs = [_agent("A", None, 0.9), _agent("B", None, 0.9), _agent("C", None, 0.4)]
    decision = await _finalize(outputs)

    assert [e.agent_name for e in decision.minority_report] == ["C"]
    assert "below the group mean" in decision.minority_report[0].dissent_reason


# --- critique replies: schema and sanitizing ----------------------------------

def _critique(critic: str, target: str = "Risk", severity: str = "high", round_number: int = 1) -> CritiqueResponse:
    return CritiqueResponse(
        critic_agent=critic, target_agent=target, round_number=round_number,
        critique_points=[f"{critic} sees a gap"], severity=severity,  # type: ignore[arg-type]
        confidence_score=0.8,
    )


def _reply(critic: str, status: str, note: str = "") -> CritiqueReply:
    return CritiqueReply(critic_agent=critic, status=status, note=note)  # type: ignore[arg-type]


def _llm_returning(replies: list[CritiqueReply]) -> MagicMock:
    llm = MagicMock()
    llm.provider, llm.model = "groq", "test-model"
    llm.ainvoke_structured = AsyncMock(return_value=AgentLLMOutput(
        position="Revised.", reasoning="r", confidence_score=0.8, stance="support",
        critique_replies=replies,
    ))
    return llm


def test_critique_replies_are_optional_everywhere():
    assert "critique_replies" not in AgentLLMOutput.model_json_schema().get("required", [])
    assert "critique_replies" in EthicsLLMOutput.model_fields
    assert "critique_replies" not in AgentResponse.model_json_schema().get("required", [])


def test_a_debate_stored_before_critique_replies_existed_still_loads():
    state = DebateState.model_validate({
        "user_query": QUERY,
        "current_round": 1,
        "rounds": [{
            "round_number": 1,
            "agent_outputs": [{
                "agent_name": "Risk", "round_number": 1, "position": "Too risky.",
                "reasoning": "r", "confidence_score": 0.7, "stance": "oppose",
            }],
        }],
    })
    assert state.rounds[0].agent_outputs[0].critique_replies == []


@pytest.mark.anyio
async def test_a_revision_keeps_one_reply_per_critic_who_critiqued_it():
    llm = _llm_returning([
        _reply("Strategy", "unaddressed"),
        _reply("Analyst", "addressed", "never critiqued Risk"),
        _reply("ethics ", "rebutted", "case and spacing differ"),
        _reply("Strategy", "addressed", "added a pilot phase"),
    ])
    state = DebateState(user_query=QUERY, current_round=1)
    response = await RiskAgent(llm_client=llm).revise(state, [_critique("Strategy"), _critique("Ethics")])

    assert [(r.critic_agent, r.status) for r in response.critique_replies] == [
        ("Strategy", "addressed"),  # the last answer wins
        ("Ethics", "rebutted"),     # stored under the critic's real name
    ]


@pytest.mark.anyio
async def test_a_proposal_never_carries_critique_replies():
    llm = _llm_returning([_reply("Strategy", "addressed")])
    response = await RiskAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=2))
    assert response.critique_replies == []


# --- revision prompts ---------------------------------------------------------

def _prompt(llm: MagicMock) -> str:
    return llm.ainvoke_structured.call_args.kwargs["user_prompt"]


@pytest.mark.anyio
@pytest.mark.parametrize("agent_cls", [
    AnalystAgent, RiskAgent, StrategyAgent, EthicsAgent, SecurityAgent, FinancialEthicsAgent,
])
async def test_every_revision_prompt_asks_for_a_reply_per_critic(agent_cls):
    llm = _llm_returning([])
    critiques = [_critique("Strategy", severity="critical"), _critique("Ethics"), _critique("Strategy")]
    await agent_cls(llm_client=llm).revise(DebateState(user_query=QUERY, current_round=1), critiques)

    prompt = _prompt(llm)
    assert CRITIQUE_REPLY_INSTRUCTION in prompt
    assert "Critics to answer: Strategy, Ethics." in prompt
    # Each critique is listed with who raised it and how serious it is.
    assert "From Strategy (severity=critical)" in prompt and "From Ethics (severity=high)" in prompt


@pytest.mark.anyio
async def test_proposals_and_uncritiqued_revisions_get_no_reply_instruction():
    proposal_llm, revision_llm = _llm_returning([]), _llm_returning([])
    state = DebateState(user_query=QUERY, current_round=1)
    await RiskAgent(llm_client=proposal_llm).run(state)
    await RiskAgent(llm_client=revision_llm).revise(state, [])

    assert "critique_replies" not in _prompt(proposal_llm)
    assert "critique_replies" not in _prompt(revision_llm)
