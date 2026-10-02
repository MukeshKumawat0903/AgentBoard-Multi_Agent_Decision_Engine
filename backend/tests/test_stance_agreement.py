"""Stance-based agreement: the structured verdict each agent declares, and how
the convergence node turns it into the agreement score."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import AgentLLMOutput
from app.agents.ethics_agent import EthicsAgent, EthicsLLMOutput
from app.agents.risk_agent import RiskAgent
from app.core.config import settings as app_settings
from app.main import app
from app.orchestrator.nodes import make_convergence_node
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
async def test_the_same_split_passes_under_the_legacy_lexical_method():
    """Documents the bug stance fixes: word overlap reads opposite verdicts as agreement."""
    outputs = [_voter(n, s) for n, s in TWO_VS_TWO]
    result, _ = await _run_convergence(_graph_state(outputs, agreement_method="lexical"), _settings())

    assert result["debate_state"].rounds[-1].agreement_method_used == "lexical"
    assert result["debate_state"].termination_reason == "consensus_reached"


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
async def test_start_async_stores_the_resolved_method(monkeypatch):
    monkeypatch.setattr(app_settings, "AGREEMENT_METHOD", "stance")
    captured: list[DebateState] = []

    async def _fake_persist(state, _db):
        captured.append(state)

    graph = MagicMock()
    graph.run = AsyncMock(side_effect=lambda *a, **k: (k["initial_state"], None))
    with (
        patch("app.api.routes.DebateGraph", return_value=graph),
        patch("app.api.routes._persist_debate_state", side_effect=_fake_persist),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
            await client.post("/debate/start-async", json={"query": QUERY})
            await client.post("/debate/start-async", json={"query": QUERY, "agreement_method": "lexical"})

    # Background runs may persist again; take each debate's first snapshot.
    first_seen = dict.fromkeys((s.thread_id, s.agreement_method) for s in captured)
    assert [method for _, method in first_seen] == ["stance", "lexical"]
