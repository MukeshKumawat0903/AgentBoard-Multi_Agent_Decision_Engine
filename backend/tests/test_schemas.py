"""
Tests for Phase 3 core schemas.

Covers:
- Valid construction of all models
- Automatic default generation (thread_id UUID, timestamps)
- Field constraint enforcement (confidence_score range, severity enum, query length)
- JSON schema export
- DebateState convenience helpers
- FinalDecision debate_trace nesting
- API model round-trips
"""

import re
import uuid
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateRound, DebateState
from app.schemas.final_decision import FinalDecision
from app.schemas.api_models import (
    DebateStartRequest,
    DebateStartResponse,
    DebateStatusResponse,
    ErrorResponse,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _make_agent_response(**overrides: Any) -> AgentResponse:
    defaults = dict(
        agent_name="Analyst",
        round_number=1,
        position="Option A is superior.",
        reasoning="Cost savings of 23%.",
        assumptions=["Market is stable"],
        confidence_score=0.8,
    )
    return AgentResponse(**(defaults | overrides))  # type: ignore[arg-type]


def _make_critique(**overrides: Any) -> CritiqueResponse:
    defaults = dict(
        critic_agent="Risk",
        target_agent="Analyst",
        round_number=1,
        critique_points=["Ignores tail risk"],
        severity="high",
        confidence_score=0.75,
    )
    return CritiqueResponse(**(defaults | overrides))  # type: ignore[arg-type]


def _make_debate_state(**overrides: Any) -> DebateState:
    defaults = dict(user_query="Should we expand internationally in Q3?")
    return DebateState(**(defaults | overrides))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AgentResponse
# ---------------------------------------------------------------------------


def test_agent_response_valid_construction():
    r = _make_agent_response()
    assert r.agent_name == "Analyst"
    assert r.round_number == 1
    assert 0.0 <= r.confidence_score <= 1.0
    assert isinstance(r.timestamp, datetime)


def test_agent_response_defaults():
    r = _make_agent_response()
    assert r.assumptions == ["Market is stable"]
    # timestamp auto-set
    assert r.timestamp is not None


def test_agent_response_confidence_too_high():
    with pytest.raises(ValidationError) as exc_info:
        _make_agent_response(confidence_score=1.5)
    assert "confidence_score" in str(exc_info.value)


def test_agent_response_confidence_negative():
    with pytest.raises(ValidationError) as exc_info:
        _make_agent_response(confidence_score=-0.1)
    assert "confidence_score" in str(exc_info.value)


def test_agent_response_confidence_boundary_values():
    lo = _make_agent_response(confidence_score=0.0)
    hi = _make_agent_response(confidence_score=1.0)
    assert lo.confidence_score == 0.0
    assert hi.confidence_score == 1.0


def test_agent_response_json_schema():
    schema = AgentResponse.model_json_schema()
    assert "properties" in schema
    assert "confidence_score" in schema["properties"]


def test_agent_response_serialization_round_trip():
    r = _make_agent_response()
    data = r.model_dump()
    restored = AgentResponse.model_validate(data)
    assert restored.agent_name == r.agent_name
    assert restored.confidence_score == r.confidence_score


# ---------------------------------------------------------------------------
# CritiqueResponse
# ---------------------------------------------------------------------------


def test_critique_valid_severities():
    for sev in ("low", "medium", "high", "critical"):
        c = _make_critique(severity=sev)
        assert c.severity == sev


def test_critique_invalid_severity():
    with pytest.raises(ValidationError) as exc_info:
        _make_critique(severity="extreme")
    assert "severity" in str(exc_info.value)


def test_critique_optional_suggested_revision_default():
    c = _make_critique()
    assert c.suggested_revision is None


def test_critique_suggested_revision_set():
    c = _make_critique(suggested_revision="Add a risk matrix.")
    assert c.suggested_revision == "Add a risk matrix."


def test_critique_confidence_bounds():
    with pytest.raises(ValidationError):
        _make_critique(confidence_score=2.0)


def test_critique_json_schema():
    schema = CritiqueResponse.model_json_schema()
    assert "severity" in schema["properties"]


# ---------------------------------------------------------------------------
# DebateRound
# ---------------------------------------------------------------------------


def test_debate_round_defaults():
    r = DebateRound(round_number=1)
    assert r.phase == "proposal"
    assert r.agent_outputs == []
    assert r.critiques == []


def test_debate_round_accepts_outputs():
    output = _make_agent_response()
    critique = _make_critique()
    r = DebateRound(round_number=1, agent_outputs=[output], critiques=[critique])
    assert len(r.agent_outputs) == 1
    assert len(r.critiques) == 1


def test_debate_round_invalid_phase():
    with pytest.raises(ValidationError):
        DebateRound(round_number=1, phase="unknown_phase")  # type: ignore[arg-type]


def test_debate_round_json_schema():
    schema = DebateRound.model_json_schema()
    assert "round_number" in schema["properties"]


# ---------------------------------------------------------------------------
# DebateState
# ---------------------------------------------------------------------------


def test_debate_state_thread_id_is_uuid():
    s = _make_debate_state()
    assert UUID_RE.match(s.thread_id), f"Not a UUID: {s.thread_id}"


def test_debate_state_two_instances_have_different_thread_ids():
    a = _make_debate_state()
    b = _make_debate_state()
    assert a.thread_id != b.thread_id


def test_debate_state_defaults():
    s = _make_debate_state()
    assert s.current_round == 0
    assert s.max_rounds == 4
    assert s.status == "initialized"
    assert s.agreement_score == 0.0
    assert s.rounds == []
    assert s.confidence_scores == {}
    assert s.termination_reason is None


def test_debate_state_status_can_be_updated():
    s = _make_debate_state()
    s.status = "in_progress"
    assert s.status == "in_progress"


def test_debate_state_invalid_status():
    with pytest.raises(ValidationError):
        DebateState(user_query="Should we expand?", status="flying")  # type: ignore[arg-type]


def test_debate_state_query_too_short():
    with pytest.raises(ValidationError):
        DebateState(user_query="Short")


def test_debate_state_agreement_score_bounds():
    with pytest.raises(ValidationError):
        DebateState(user_query="Should we expand internationally in Q3?", agreement_score=1.5)


def test_debate_state_latest_outputs_empty():
    s = _make_debate_state()
    assert s.latest_outputs() == []


def test_debate_state_latest_critiques_empty():
    s = _make_debate_state()
    assert s.latest_critiques() == []


def test_debate_state_convenience_helpers_with_rounds():
    output = _make_agent_response()
    critique = _make_critique()
    round_ = DebateRound(round_number=1, agent_outputs=[output], critiques=[critique])
    s = _make_debate_state()
    s.rounds.append(round_)

    assert len(s.latest_outputs()) == 1
    assert len(s.latest_critiques()) == 1


def test_debate_state_current_round_data():
    s = _make_debate_state()
    s.current_round = 1
    r1 = DebateRound(round_number=1)
    s.rounds.append(r1)
    assert s.current_round_data() is r1


def test_debate_state_current_round_data_none_when_not_started():
    s = _make_debate_state()
    assert s.current_round_data() is None


def test_debate_state_touch_updates_timestamp():
    s = _make_debate_state()
    original = s.updated_at
    import time
    time.sleep(0.01)
    s.touch()
    assert s.updated_at > original


def test_debate_state_json_schema():
    schema = DebateState.model_json_schema()
    assert "thread_id" in schema["properties"]
    assert "status" in schema["properties"]


# ---------------------------------------------------------------------------
# FinalDecision
# ---------------------------------------------------------------------------


def _make_final_decision(**overrides: Any) -> FinalDecision:
    defaults = dict(
        thread_id=str(uuid.uuid4()),
        decision="Proceed with phased expansion.",
        rationale_summary="All agents reached 87% agreement.",
        confidence_score=0.85,
        agreement_score=0.87,
        total_rounds=3,
        termination_reason="consensus_reached",
    )
    return FinalDecision(**(defaults | overrides))  # type: ignore[arg-type]


def test_final_decision_valid():
    d = _make_final_decision()
    assert d.total_rounds == 3
    assert d.risk_flags == []
    assert d.alternatives == []
    assert d.dissenting_opinions == []
    assert d.debate_trace == []


def test_final_decision_confidence_bounds():
    with pytest.raises(ValidationError):
        _make_final_decision(confidence_score=1.1)


def test_final_decision_agreement_bounds():
    with pytest.raises(ValidationError):
        _make_final_decision(agreement_score=-0.5)


def test_final_decision_stores_debate_trace():
    r1 = DebateRound(round_number=1)
    r2 = DebateRound(round_number=2, phase="critique")
    d = _make_final_decision(debate_trace=[r1, r2])
    assert len(d.debate_trace) == 2
    assert d.debate_trace[1].phase == "critique"


def test_final_decision_json_schema():
    schema = FinalDecision.model_json_schema()
    assert "decision" in schema["properties"]
    assert "debate_trace" in schema["properties"]


def test_final_decision_serialization_round_trip():
    d = _make_final_decision()
    restored = FinalDecision.model_validate(d.model_dump())
    assert restored.decision == d.decision
    assert restored.thread_id == d.thread_id


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------


def test_debate_start_request_valid():
    req = DebateStartRequest(query="Should we expand internationally in Q3?")
    assert req.max_rounds == 4
    assert req.agents is None


def test_debate_start_request_custom():
    req = DebateStartRequest(
        query="Should we expand internationally in Q3?",
        max_rounds=6,
        agents=["Analyst", "Risk"],
    )
    assert req.max_rounds == 6
    assert req.agents == ["Analyst", "Risk"]


def test_debate_start_request_query_too_short():
    with pytest.raises(ValidationError):
        DebateStartRequest(query="Short")


def test_debate_start_request_query_too_long():
    with pytest.raises(ValidationError):
        DebateStartRequest(query="x" * 5001)


def test_debate_start_request_max_rounds_out_of_range():
    with pytest.raises(ValidationError):
        DebateStartRequest(query="Should we expand internationally in Q3?", max_rounds=1)
    with pytest.raises(ValidationError):
        DebateStartRequest(query="Should we expand internationally in Q3?", max_rounds=9)


def test_debate_start_response_valid():
    resp = DebateStartResponse(
        thread_id=str(uuid.uuid4()),
        status="in_progress",
        message="Started.",
    )
    assert resp.status == "in_progress"


def test_debate_status_response_valid():
    resp = DebateStatusResponse(
        thread_id=str(uuid.uuid4()),
        status="in_progress",
        current_round=2,
        total_rounds=4,
        agreement_score=0.6,
        rounds=[],
    )
    assert resp.current_round == 2


def test_debate_status_agreement_score_bounds():
    with pytest.raises(ValidationError):
        DebateStatusResponse(
            thread_id=str(uuid.uuid4()),
            status="in_progress",
            current_round=1,
            total_rounds=4,
            agreement_score=1.5,
            rounds=[],
        )


def test_error_response_valid():
    e = ErrorResponse(error="not_found", detail="No debate found.")
    assert e.error == "not_found"
    assert e.detail == "No debate found."


def test_error_response_detail_optional():
    e = ErrorResponse(error="server_error")
    assert e.detail is None


def test_api_models_json_schemas_export():
    for model in (DebateStartRequest, DebateStartResponse, DebateStatusResponse, ErrorResponse):
        schema = model.model_json_schema()
        assert "properties" in schema
