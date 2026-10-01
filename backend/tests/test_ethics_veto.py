"""
The Ethics veto is structured: Ethics-class agents return veto/veto_reason, a
standing veto blocks consensus, and the final decision (and its exports) lists
the vetoes that still stood when the debate ended.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import AgentLLMOutput
from app.agents.domain_agents import FinancialEthicsAgent, PatientSafetyAgent, SecurityAgent
from app.agents.ethics_agent import EthicsAgent, EthicsLLMOutput
from app.agents.moderator_agent import FinalDecisionLLMOutput, ModeratorAgent
from app.orchestrator.debate_graph import _CHECKPOINT_SERDE
from app.orchestrator.lg_state import DebateGraphState
from app.orchestrator.nodes import make_convergence_node
from app.schemas.agent_response import AgentResponse
from app.schemas.final_decision import FinalDecision, VetoEntry
from app.schemas.state import DebateRound, DebateState
from app.services.consensus import ConsensusSignals, is_consensus_reached
from app.services.exporter import render_html, render_markdown
from tests.test_orchestrator import _mock_settings, _synthesis

QUERY = "Should we sell customer location data to advertisers?"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _llm(result) -> MagicMock:
    llm = MagicMock()
    llm.provider, llm.model = "groq", "test-model"
    llm.ainvoke_structured = AsyncMock(return_value=result)
    return llm


def _ethics_output(veto: bool, reason: str | None = None) -> EthicsLLMOutput:
    return EthicsLLMOutput(
        position="Selling the data breaches user consent.", reasoning="Consent was not given.",
        confidence_score=0.9, veto=veto, veto_reason=reason,
    )


# --- agents ------------------------------------------------------------------

@pytest.mark.anyio
async def test_ethics_agent_returns_a_structured_veto():
    llm = _llm(_ethics_output(True, "Violates informed consent; lift if users opt in."))
    response = await EthicsAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=1))

    assert llm.ainvoke_structured.call_args.args[0] is EthicsLLMOutput
    assert response.veto is True
    assert response.veto_reason == "Violates informed consent; lift if users opt in."


@pytest.mark.anyio
async def test_a_withdrawn_veto_drops_its_reason():
    llm = _llm(_ethics_output(False, "left over text"))
    response = await EthicsAgent(llm_client=llm).revise(DebateState(user_query=QUERY, current_round=2), [])
    assert (response.veto, response.veto_reason) == (False, None)


@pytest.mark.anyio
async def test_other_agents_keep_the_plain_schema():
    llm = _llm(AgentLLMOutput(position="Proceed.", reasoning="Revenue.", confidence_score=0.7))
    response = await AnalystAgent(llm_client=llm).run(DebateState(user_query=QUERY, current_round=1))

    assert llm.ainvoke_structured.call_args.args[0] is AgentLLMOutput
    assert response.veto is False


def test_ethics_class_domain_agents_can_veto():
    assert FinancialEthicsAgent.output_schema is EthicsLLMOutput
    assert PatientSafetyAgent.output_schema is EthicsLLMOutput
    assert SecurityAgent.output_schema is AgentLLMOutput


# --- gate ----------------------------------------------------------------------

def test_a_standing_veto_blocks_an_otherwise_clean_consensus():
    clean = dict(position_agreement=1.0, rounds_completed=3, dissenting_agents=0,
                 open_disagreements=0, confidence_converged=True)
    gate = dict(threshold=0.75, min_rounds=1, max_dissent=1, max_open_disagreements=2)
    assert is_consensus_reached(ConsensusSignals(**clean), **gate) is True
    assert is_consensus_reached(ConsensusSignals(**clean, active_vetoes=1), **gate) is False


def _agreeing_round(veto: bool) -> DebateRound:
    position = "Proceed with an opt-in programme and strict anonymisation."
    outputs = [
        AgentResponse(agent_name=name, round_number=2, position=position, reasoning="r", confidence_score=0.95)
        for name in ("Analyst", "Risk", "Strategy")
    ]
    outputs.append(AgentResponse(
        agent_name="Ethics", round_number=2, position=position, reasoning="r", confidence_score=0.95,
        veto=veto, veto_reason="Still no consent." if veto else None,
    ))
    return DebateRound(round_number=2, agent_outputs=outputs)


@pytest.mark.anyio
@pytest.mark.parametrize(("veto", "max_rounds", "expected_reason"), [
    (False, 4, "consensus_reached"),
    (True, 4, None),                    # keeps debating
    (True, 2, "max_rounds_reached"),    # out of rounds: ends without consensus
])
async def test_convergence_node_respects_vetoes(veto, max_rounds, expected_reason):
    moderator = MagicMock()
    moderator.synthesize = AsyncMock(return_value=_synthesis(agreement_score=0.95, should_continue=False))
    state = DebateState(
        user_query=QUERY, current_round=2, max_rounds=max_rounds, min_rounds=1,
        rounds=[DebateRound(round_number=1), _agreeing_round(veto)],
    )
    graph_state: DebateGraphState = {"debate_state": state, "should_continue": True, "final_decision": None}

    result = await make_convergence_node(moderator, _mock_settings(), MagicMock(), AsyncMock())(graph_state)

    assert state.termination_reason == expected_reason
    assert result["should_continue"] is (expected_reason is None)


# --- decision ------------------------------------------------------------------

@pytest.mark.anyio
async def test_final_decision_lists_standing_vetoes_and_the_prompt_mentions_them():
    llm = _llm(FinalDecisionLLMOutput(decision="Do not sell the data.", rationale_summary="Consent.",
                                      confidence_score=0.8, agreement_score=0.6))
    state = DebateState(user_query=QUERY, current_round=2, max_rounds=2,
                        termination_reason="max_rounds_reached",
                        rounds=[DebateRound(round_number=1), _agreeing_round(True)])

    decision = await ModeratorAgent(llm_client=llm).finalize(state)

    assert decision.vetoes == [VetoEntry(agent_name="Ethics", reason="Still no consent.", round_number=2)]
    prompt = llm.ainvoke_structured.call_args.kwargs["user_prompt"]
    assert "Standing ethics vetoes" in prompt and "- Ethics: Still no consent." in prompt


@pytest.mark.anyio
async def test_no_vetoes_means_no_veto_text():
    llm = _llm(FinalDecisionLLMOutput(decision="Proceed.", rationale_summary="ok",
                                      confidence_score=0.8, agreement_score=0.9))
    state = DebateState(user_query=QUERY, current_round=2, rounds=[_agreeing_round(False)])

    decision = await ModeratorAgent(llm_client=llm).finalize(state)

    assert decision.vetoes == []
    assert "veto" not in llm.ainvoke_structured.call_args.kwargs["user_prompt"].lower()


def _vetoed_decision() -> FinalDecision:
    return FinalDecision(
        thread_id="t-veto", decision="Do not sell the data.", rationale_summary="Consent.",
        confidence_score=0.8, agreement_score=0.6, total_rounds=2, termination_reason="max_rounds_reached",
        vetoes=[VetoEntry(agent_name="Ethics", reason="No consent <given>.", round_number=2)],
    )


def test_exports_list_the_vetoes():
    assert "## Standing Vetoes" in render_markdown(_vetoed_decision())
    assert "**Ethics** (round 2): No consent <given>." in render_markdown(_vetoed_decision())
    html = render_html(_vetoed_decision())
    assert "<h2>Standing Vetoes</h2>" in html and "No consent &lt;given&gt;." in html


def test_vetoes_survive_a_checkpoint_round_trip():
    state = DebateState(user_query=QUERY, current_round=2, rounds=[_agreeing_round(True)])
    payload = {"debate_state": state, "final_decision": _vetoed_decision()}

    restored = _CHECKPOINT_SERDE.loads_typed(_CHECKPOINT_SERDE.dumps_typed(payload))

    assert restored["debate_state"].rounds[0].agent_outputs[-1].veto is True
    assert restored["final_decision"].vetoes == _vetoed_decision().vetoes
