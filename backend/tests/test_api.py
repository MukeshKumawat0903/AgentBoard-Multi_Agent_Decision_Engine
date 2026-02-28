"""
Tests for API endpoints (Phase 8).

All DebateController calls are mocked – no LLM traffic.

Coverage:
  GET  /health                   – 200 + correct fields
  POST /debate/start             – 200 FinalDecision; LLM errors → 502/503/429
  GET  /debate/{thread_id}       – 200 DebateStatusResponse; 404 unknown
  GET  /decision/{thread_id}     – 200 FinalDecision; 404 unknown; 409 in-progress
  Exception handlers             – LLMResponseError→502, LLMConnectionError→503,
                                   LLMRateLimitError→429, generic Exception→500
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient, ASGITransport

from app.api.dependencies import get_debate_store, get_decision_store
from app.main import app
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.utils.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def isolated_stores():
    """
    Inject fresh, isolated in-memory stores via FastAPI dependency_overrides.
    Cleaned up after each test.
    """
    debate_store: dict[str, DebateState] = {}
    decision_store: dict[str, FinalDecision] = {}

    app.dependency_overrides[get_debate_store] = lambda: debate_store
    app.dependency_overrides[get_decision_store] = lambda: decision_store

    yield debate_store, decision_store

    app.dependency_overrides.pop(get_debate_store, None)
    app.dependency_overrides.pop(get_decision_store, None)


@pytest.fixture
async def client():
    """Async HTTPX test client backed by the FastAPI application."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Domain object helpers
# ---------------------------------------------------------------------------

def _make_state(**kwargs: Any) -> DebateState:
    defaults: dict[str, Any] = {
        "user_query": "Should we expand into the Asian market in Q3?",
        "current_round": 1,
        "status": "converged",
        "agreement_score": 0.85,
    }
    return DebateState(**{**defaults, **kwargs})


def _make_decision(thread_id: str | None = None, **kwargs: Any) -> FinalDecision:
    tid = thread_id or str(uuid4())
    defaults: dict[str, Any] = {
        "thread_id": tid,
        "decision": "Proceed with phased expansion.",
        "rationale_summary": "Consensus after 2 rounds.",
        "confidence_score": 0.87,
        "agreement_score": 0.85,
        "total_rounds": 2,
        "termination_reason": "consensus_reached",
    }
    return FinalDecision(**{**defaults, **kwargs})


def _mock_controller(state: DebateState, decision: FinalDecision) -> MagicMock:
    """Return a MagicMock that mimics DebateController's async API."""
    ctrl = MagicMock()
    ctrl.initialize_state = AsyncMock(return_value=state)
    ctrl.execute = AsyncMock(return_value=decision)
    return ctrl


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthCheck:

    @pytest.mark.anyio
    async def test_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_status_ok(self, client):
        data = (await client.get("/health")).json()
        assert data["status"] == "ok"

    @pytest.mark.anyio
    async def test_version_present(self, client):
        data = (await client.get("/health")).json()
        assert data["version"] == "0.1.0"

    @pytest.mark.anyio
    async def test_groq_configured_present(self, client):
        data = (await client.get("/health")).json()
        assert "groq_configured" in data


# ---------------------------------------------------------------------------
# POST /debate/start
# ---------------------------------------------------------------------------

class TestPostDebateStart:

    @pytest.mark.anyio
    async def test_returns_200_with_final_decision(self, client, isolated_stores):
        debate_store, decision_store = isolated_stores
        state = _make_state()
        decision = _make_decision(thread_id=state.thread_id)

        with patch("app.api.routes.DebateController", return_value=_mock_controller(state, decision)):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?", "max_rounds": 2},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "Proceed with phased expansion."
        assert body["thread_id"] == state.thread_id

    @pytest.mark.anyio
    async def test_stores_state_and_decision(self, client, isolated_stores):
        debate_store, decision_store = isolated_stores
        state = _make_state()
        decision = _make_decision(thread_id=state.thread_id)

        with patch("app.api.routes.DebateController", return_value=_mock_controller(state, decision)):
            await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?", "max_rounds": 2},
            )

        assert state.thread_id in debate_store
        assert state.thread_id in decision_store

    @pytest.mark.anyio
    async def test_validation_error_on_short_query(self, client, isolated_stores):
        response = await client.post("/debate/start", json={"query": "short"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_validation_error_on_max_rounds_too_small(self, client, isolated_stores):
        response = await client.post(
            "/debate/start",
            json={"query": "Should we expand into the Asian market in Q3?", "max_rounds": 1},
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_missing_body_returns_422(self, client, isolated_stores):
        response = await client.post("/debate/start")
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_llm_response_error_returns_502(self, client, isolated_stores):
        debate_store, _ = isolated_stores
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMResponseError("bad JSON from model"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert response.status_code == 502
        assert response.json()["error"] == "llm_response_error"

    @pytest.mark.anyio
    async def test_llm_connection_error_returns_503(self, client, isolated_stores):
        debate_store, _ = isolated_stores
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMConnectionError("network timeout"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert response.status_code == 503
        assert response.json()["error"] == "llm_connection_error"

    @pytest.mark.anyio
    async def test_llm_rate_limit_error_returns_429(self, client, isolated_stores):
        debate_store, _ = isolated_stores
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMRateLimitError("rate limited"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert response.status_code == 429
        assert response.json()["error"] == "llm_rate_limit"

    @pytest.mark.anyio
    async def test_state_marked_error_on_execute_failure(self, client, isolated_stores):
        debate_store, _ = isolated_stores
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMConnectionError("timeout"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert state.status == "error"


# ---------------------------------------------------------------------------
# GET /debate/{thread_id}
# ---------------------------------------------------------------------------

class TestGetDebateStatus:

    @pytest.mark.anyio
    async def test_returns_200_for_known_thread(self, client, isolated_stores):
        debate_store, _ = isolated_stores
        state = _make_state()
        debate_store[state.thread_id] = state

        response = await client.get(f"/debate/{state.thread_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["thread_id"] == state.thread_id
        assert body["status"] == "converged"

    @pytest.mark.anyio
    async def test_response_contains_required_fields(self, client, isolated_stores):
        debate_store, _ = isolated_stores
        state = _make_state(
            current_round=2,
            agreement_score=0.88,
            rounds=[DebateRound(round_number=1), DebateRound(round_number=2)],
        )
        debate_store[state.thread_id] = state

        body = (await client.get(f"/debate/{state.thread_id}")).json()

        assert body["current_round"] == 2
        assert body["agreement_score"] == pytest.approx(0.88)
        assert len(body["rounds"]) == 2

    @pytest.mark.anyio
    async def test_returns_404_for_unknown_thread(self, client, isolated_stores):
        response = await client.get("/debate/unknown-thread-id")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_404_has_error_response_body(self, client, isolated_stores):
        response = await client.get("/debate/ghost-id")
        body = response.json()
        assert "detail" in body
        assert body["detail"]["error"] == "debate_not_found"


# ---------------------------------------------------------------------------
# GET /decision/{thread_id}
# ---------------------------------------------------------------------------

class TestGetDecision:

    @pytest.mark.anyio
    async def test_returns_200_for_completed_debate(self, client, isolated_stores):
        debate_store, decision_store = isolated_stores
        state = _make_state()
        decision = _make_decision(thread_id=state.thread_id)
        debate_store[state.thread_id] = state
        decision_store[state.thread_id] = decision

        response = await client.get(f"/decision/{state.thread_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["thread_id"] == state.thread_id
        assert body["decision"] == "Proceed with phased expansion."

    @pytest.mark.anyio
    async def test_returns_404_for_unknown_thread(self, client, isolated_stores):
        response = await client.get("/decision/no-such-thread")
        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "debate_not_found"

    @pytest.mark.anyio
    async def test_returns_409_when_debate_still_running(self, client, isolated_stores):
        debate_store, decision_store = isolated_stores
        state = _make_state(status="in_progress")
        debate_store[state.thread_id] = state
        # decision_store intentionally empty – debate not finished

        response = await client.get(f"/decision/{state.thread_id}")

        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "debate_in_progress"

    @pytest.mark.anyio
    async def test_decision_contains_full_schema(self, client, isolated_stores):
        debate_store, decision_store = isolated_stores
        state = _make_state()
        decision = _make_decision(
            thread_id=state.thread_id,
            risk_flags=["Currency risk"],
            alternatives=["Delay to Q4"],
        )
        debate_store[state.thread_id] = state
        decision_store[state.thread_id] = decision

        body = (await client.get(f"/decision/{state.thread_id}")).json()

        assert body["risk_flags"] == ["Currency risk"]
        assert body["alternatives"] == ["Delay to Q4"]
        assert body["termination_reason"] == "consensus_reached"


# ---------------------------------------------------------------------------
# Exception handler integration
# ---------------------------------------------------------------------------

class TestExceptionHandlers:

    @pytest.mark.anyio
    async def test_llm_response_error_returns_502_error_key(self, client, isolated_stores):
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMResponseError("parse failed"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert response.status_code == 502
        data = response.json()
        assert data["error"] == "llm_response_error"
        assert "parse failed" in data["detail"]

    @pytest.mark.anyio
    async def test_llm_connection_error_detail_propagated(self, client, isolated_stores):
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMConnectionError("unreachable"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert "unreachable" in response.json()["detail"]

    @pytest.mark.anyio
    async def test_rate_limit_error_returns_429(self, client, isolated_stores):
        state = _make_state()
        ctrl = MagicMock()
        ctrl.initialize_state = AsyncMock(return_value=state)
        ctrl.execute = AsyncMock(side_effect=LLMRateLimitError("too many requests"))

        with patch("app.api.routes.DebateController", return_value=ctrl):
            response = await client.post(
                "/debate/start",
                json={"query": "Should we expand into the Asian market in Q3?"},
            )

        assert response.status_code == 429

