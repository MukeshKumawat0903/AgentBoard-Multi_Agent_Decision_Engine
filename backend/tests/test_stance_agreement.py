"""Stance-based agreement: the structured verdict each agent declares, and how
the convergence node turns it into the agreement score."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.agents.analyst_agent import AnalystAgent
from app.agents.moderator_agent import ModeratorAgent
from app.agents.base_agent import AgentLLMOutput
from app.agents.ethics_agent import EthicsAgent, EthicsLLMOutput
from app.agents.risk_agent import RiskAgent
from app.core.config import settings as app_settings
from app.main import app
from app.orchestrator.nodes import make_convergence_node, make_finalize_node, make_proposals_node
from app.schemas.agent_response import AgentResponse
from app.schemas.api_models import DebateStartRequest, SimulateRequest
from app.schemas.state import DebateRound, DebateState
from tests.test_orchestrator import _mock_settings, _synthesis

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
    assert state.rounds[0].leading_proposal is None
    assert state.rounds[0].agreement_method_used is None
    assert state.agreement_method is None


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


# --- convergence node: method selection --------------------------------------

def _voter(name: str, stance: str | None, confidence: float = 0.85, round_number: int = 2) -> AgentResponse:
    # Identical wording on purpose: word overlap scores these as fully agreeing,
    # whatever their verdict, which is exactly the blind spot stance removes.
    return AgentResponse(
        agent_name=name, round_number=round_number,
        position="We should decide on the Southeast Asia expansion next year.",
        reasoning="r", confidence_score=confidence, stance=stance,
    )


def _graph_state(outputs: list[AgentResponse], *, agreement_method=None, current_round: int = 2):
    debate_state = DebateState(
        user_query=QUERY,
        current_round=current_round,
        max_rounds=4,
        agreement_method=agreement_method,
        rounds=[DebateRound(round_number=current_round, agent_outputs=outputs)],
    )
    return {"debate_state": debate_state, "should_continue": True, "final_decision": None}


def _settings(method: str = "stance", *, semantic_enabled: bool = False):
    settings = _mock_settings(semantic_enabled=semantic_enabled)
    settings.AGREEMENT_METHOD = method
    return settings


async def _run_convergence(graph_state, settings, *, semantic_score: float | None = None):
    emit = MagicMock()
    moderator = MagicMock()
    moderator.synthesize = AsyncMock(return_value=_synthesis(agreement_score=0.9, should_continue=False))
    with patch("app.orchestrator.nodes.SemanticConsensusEngine") as engine_cls:
        engine_cls.return_value.compute_semantic_similarity.return_value = semantic_score
        node = make_convergence_node(moderator, settings, emit, AsyncMock())
        result = await node(graph_state)
    synthesis = next(c.args[1] for c in emit.call_args_list if c.args[0] == "synthesis")
    return result, synthesis


TWO_VS_TWO = [
    ("Risk", "oppose"), ("Strategy", "support"), ("Ethics", "oppose"), ("Finance", "support"),
]


@pytest.mark.anyio
async def test_a_two_vs_two_split_never_reaches_consensus_by_default():
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, _ = await _run_convergence(_graph_state(outputs), _settings())

    ds = result["debate_state"]
    assert ds.agreement_score == pytest.approx(0.5)
    assert ds.rounds[-1].agreement_method_used == "stance"
    assert result["should_continue"] is True
    assert ds.termination_reason != "consensus_reached"


@pytest.mark.anyio
async def test_the_same_split_passes_rule_one_under_the_legacy_lexical_method():
    """Documents the bug stance fixes: word overlap reads opposite verdicts as agreement."""
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, _ = await _run_convergence(_graph_state(outputs, agreement_method="lexical"), _settings())

    ds = result["debate_state"]
    assert ds.rounds[-1].agreement_method_used == "lexical"
    assert ds.agreement_score >= 0.75
    # This used to reach consensus. Dissent is now counted by stance, so the two
    # agents on the losing side of the split fail Rule 3 whatever Rule 1 says.
    assert ds.termination_reason != "consensus_reached"


@pytest.mark.anyio
async def test_unanimous_voters_reach_consensus_with_stance():
    outputs = [_voter("Analyst", "abstain")] + [_voter(n, "support") for n in ("Risk", "Strategy", "Ethics")]
    result, _ = await _run_convergence(_graph_state(outputs), _settings())

    assert result["debate_state"].agreement_score == pytest.approx(1.0)
    assert result["debate_state"].termination_reason == "consensus_reached"


@pytest.mark.anyio
@pytest.mark.parametrize("stances", [
    [None, None, None],                 # stored before stance existed / provider omitted it
    ["abstain", "abstain", "support"],  # only one voter
])
async def test_missing_stances_fall_back_to_lexical(stances):
    outputs = [_voter(f"A{i}", s) for i, s in enumerate(stances)]
    lexical, _ = await _run_convergence(_graph_state(list(outputs), agreement_method="lexical"), _settings())
    result, _ = await _run_convergence(_graph_state(list(outputs)), _settings())

    assert result["debate_state"].rounds[-1].agreement_method_used == "lexical"
    assert result["debate_state"].agreement_score == pytest.approx(lexical["debate_state"].agreement_score)


@pytest.mark.anyio
async def test_semantic_flag_does_not_change_the_stance_score():
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, synthesis = await _run_convergence(
        _graph_state(outputs), _settings(semantic_enabled=True), semantic_score=0.95,
    )

    hybrid = 0.5 * 0.85 + 0.5 * 0.95
    assert result["debate_state"].agreement_score == pytest.approx(0.5)
    assert result["debate_state"].agreement_score != pytest.approx(hybrid)
    assert synthesis["semantic_agreement_score"] == pytest.approx(0.95)


@pytest.mark.anyio
async def test_semantic_method_blends_confidence_and_cosine():
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, _ = await _run_convergence(
        _graph_state(outputs, agreement_method="semantic"), _settings(semantic_enabled=True),
        semantic_score=0.6,
    )

    assert result["debate_state"].agreement_score == pytest.approx(0.5 * 0.85 + 0.5 * 0.6)
    assert result["debate_state"].rounds[-1].agreement_method_used == "semantic"


@pytest.mark.anyio
async def test_semantic_method_without_the_engine_falls_back_to_lexical():
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, _ = await _run_convergence(
        _graph_state(outputs, agreement_method="semantic"), _settings(semantic_enabled=False),
    )
    assert result["debate_state"].rounds[-1].agreement_method_used == "lexical"


@pytest.mark.anyio
async def test_server_default_applies_when_the_debate_has_no_method():
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, _ = await _run_convergence(_graph_state(outputs), _settings("lexical"))
    assert result["debate_state"].rounds[-1].agreement_method_used == "lexical"


# --- API: per-debate method ----------------------------------------------------

@pytest.fixture
def semantic_off(monkeypatch):
    monkeypatch.setattr(app_settings, "SEMANTIC_CONSENSUS_ENABLED", False)


@pytest.mark.parametrize("model", [DebateStartRequest, SimulateRequest])
def test_requests_accept_an_agreement_method(model, semantic_off):
    assert model(query=QUERY, agreement_method="lexical").agreement_method == "lexical"
    assert model(query=QUERY).agreement_method is None


@pytest.mark.parametrize("model", [DebateStartRequest, SimulateRequest])
def test_semantic_is_rejected_when_unavailable(model, semantic_off):
    with pytest.raises(ValidationError, match="SEMANTIC_CONSENSUS_ENABLED"):
        model(query=QUERY, agreement_method="semantic")


def test_semantic_is_accepted_when_available(monkeypatch):
    import app.services.consensus as consensus

    monkeypatch.setattr(app_settings, "SEMANTIC_CONSENSUS_ENABLED", True)
    monkeypatch.setattr(consensus, "_SEMANTIC_AVAILABLE", True)
    assert DebateStartRequest(query=QUERY, agreement_method="semantic").agreement_method == "semantic"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/debate/start", "/debate/start-async", "/debate/simulate-async"])
async def test_api_returns_422_for_unavailable_semantic(path, semantic_off):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        resp = await client.post(path, json={"query": QUERY, "agreement_method": "semantic"})
    assert resp.status_code == 422
    assert "SEMANTIC_CONSENSUS_ENABLED" in resp.text


@pytest.mark.anyio
async def test_start_stores_the_resolved_method(monkeypatch):
    from app.api.dependencies import get_debate_store, get_decision_store
    from app.schemas.final_decision import FinalDecision

    monkeypatch.setattr(app_settings, "AGREEMENT_METHOD", "stance")
    captured: list[DebateState] = []

    async def _run(*_args, initial_state, **_kwargs):
        captured.append(initial_state)
        initial_state.current_round = 1
        return initial_state, FinalDecision(
            thread_id=initial_state.thread_id, decision="d", rationale_summary="r",
            confidence_score=0.8, agreement_score=0.8, total_rounds=1,
            termination_reason="consensus_reached",
        )

    graph = MagicMock()
    graph.run = AsyncMock(side_effect=_run)
    debate_store: dict = {}
    decision_store: dict = {}
    app.dependency_overrides[get_debate_store] = lambda: debate_store
    app.dependency_overrides[get_decision_store] = lambda: decision_store
    try:
        with patch("app.api.routes.DebateGraph", return_value=graph):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
                for body in ({"query": QUERY}, {"query": QUERY, "agreement_method": "lexical"}):
                    assert (await client.post("/debate/start", json=body)).status_code == 200
    finally:
        app.dependency_overrides.pop(get_debate_store, None)
        app.dependency_overrides.pop(get_decision_store, None)

    assert [state.agreement_method for state in captured] == ["stance", "lexical"]


# --- the stance anchor: what the stance is about --------------------------------

def _prompt_for(state: DebateState) -> str:
    return RiskAgent(llm_client=_llm(None))._stance_instruction(state)


def test_round_one_anchors_on_the_question():
    prompt = _prompt_for(DebateState(user_query=QUERY, current_round=1, rounds=[DebateRound(round_number=1)]))
    assert "Proposal on the table: the course of action the problem statement asks about" in prompt
    assert "Set `stance` toward this proposal." in prompt


def test_later_rounds_anchor_on_the_previous_leading_proposal():
    state = DebateState(user_query=QUERY, current_round=2, rounds=[
        DebateRound(round_number=1, leading_proposal="Run a Singapore pilot in Q4."),
        DebateRound(round_number=2),
    ])
    assert "Proposal on the table: Run a Singapore pilot in Q4." in _prompt_for(state)


def test_missing_leading_proposal_falls_back_to_the_question():
    state = DebateState(user_query=QUERY, current_round=3, rounds=[
        DebateRound(round_number=1, leading_proposal="An older proposal."),
        DebateRound(round_number=2, leading_proposal="  "),
        DebateRound(round_number=3),
    ])
    prompt = _prompt_for(state)
    assert "An older proposal." not in prompt
    assert "the course of action the problem statement asks about" in prompt


@pytest.mark.anyio
async def test_revision_prompt_uses_the_same_anchor():
    llm = _llm(AgentLLMOutput(position="p", reasoning="r", confidence_score=0.7, stance="support"))
    state = DebateState(user_query=QUERY, current_round=2, rounds=[
        DebateRound(round_number=1, leading_proposal="Run a Singapore pilot in Q4."),
        DebateRound(round_number=2),
    ])
    await RiskAgent(llm_client=llm).revise(state, [])
    assert "Proposal on the table: Run a Singapore pilot in Q4." in llm.ainvoke_structured.call_args.kwargs["user_prompt"]


@pytest.mark.anyio
async def test_convergence_node_stores_the_leading_proposal():
    emit = MagicMock()
    moderator = MagicMock()
    synthesis = _synthesis(agreement_score=0.5, should_continue=True)
    synthesis.leading_proposal = "  Run a Singapore pilot in Q4.  "
    moderator.synthesize = AsyncMock(return_value=synthesis)
    graph_state = _graph_state([_voter("Risk", "support"), _voter("Strategy", "support")], current_round=1)

    node = make_convergence_node(moderator, _settings(), emit, AsyncMock())
    result = await node(graph_state)

    assert result["debate_state"].rounds[-1].leading_proposal == "Run a Singapore pilot in Q4."


def test_moderator_prompt_asks_for_a_leading_proposal_and_shows_stances():
    state = DebateState(user_query=QUERY, current_round=1, rounds=[
        DebateRound(round_number=1, agent_outputs=[_voter("Risk", "oppose", round_number=1)]),
    ])
    prompt = ModeratorAgent._build_synthesis_prompt(state)
    assert "leading_proposal" in prompt
    assert "stance=oppose" in prompt


# --- events + final decision --------------------------------------------------

@pytest.mark.anyio
async def test_synthesis_event_reports_every_score_and_the_method():
    outputs = [_voter("Analyst", "abstain")] + [_voter(n, s) for n, s in TWO_VS_TWO[:3]]
    _, synthesis = await _run_convergence(
        _graph_state(outputs), _settings(semantic_enabled=True), semantic_score=0.9,
    )

    assert synthesis["agreement_method_used"] == "stance"
    assert synthesis["stance_agreement_score"] == pytest.approx(synthesis["agreement_score"])
    assert synthesis["stance_tally"] == {"abstain": 1, "oppose": 2, "support": 1}
    assert synthesis["semantic_agreement_score"] == pytest.approx(0.9)
    for key in ("confidence_agreement_score", "position_agreement_score", "leading_proposal"):
        assert key in synthesis


@pytest.mark.anyio
async def test_agent_output_events_carry_the_stance():
    agent = MagicMock()
    agent.name = "Risk"
    agent.allowed_tools = []
    agent._last_tool_calls = []
    agent.run = AsyncMock(return_value=_voter("Risk", "oppose", round_number=1))
    emit = MagicMock()
    node = make_proposals_node({"Risk": agent}, emit)
    await node({"debate_state": DebateState(user_query=QUERY), "should_continue": True, "final_decision": None})

    output_event = next(c.args[1] for c in emit.call_args_list if c.args[0] == "agent_output")
    assert output_event["stance"] == "oppose"


@pytest.mark.anyio
async def test_final_decision_records_the_method_and_tally():
    from app.schemas.final_decision import FinalDecision

    final_round = DebateRound(
        round_number=2,
        agent_outputs=[_voter("Analyst", "abstain"), _voter("Risk", "support"), _voter("Ethics", "oppose")],
        agreement_method_used="stance",
    )
    ds = DebateState(user_query=QUERY, current_round=2, rounds=[DebateRound(round_number=1), final_round],
                     termination_reason="max_rounds_reached")
    moderator = MagicMock()
    moderator.finalize = AsyncMock(return_value=FinalDecision(
        thread_id=ds.thread_id, decision="d", rationale_summary="r", confidence_score=0.8,
        agreement_score=0.5, total_rounds=2, termination_reason="max_rounds_reached",
    ))
    node = make_finalize_node(moderator, MagicMock())
    result = await node({"debate_state": ds, "should_continue": False, "final_decision": None})

    decision = result["final_decision"]
    assert decision.agreement_method == "stance"
    assert decision.stance_tally == {"abstain": 1, "support": 1, "oppose": 1}


def test_a_decision_stored_before_these_fields_still_loads():
    from app.schemas.final_decision import FinalDecision

    decision = FinalDecision.model_validate({
        "thread_id": "t", "decision": "d", "rationale_summary": "r", "confidence_score": 0.8,
        "agreement_score": 0.8, "total_rounds": 1, "termination_reason": "consensus_reached",
    })
    assert (decision.agreement_method, decision.stance_tally) == (None, None)
