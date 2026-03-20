"""Regression tests for Phase 5 observability features."""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_debate_store, get_decision_store
from app.core.logging_config import JSONFormatter
from app.core.metrics import app_metrics
from app.core.request_context import reset_request_id, set_request_id
from app.main import app
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


def _mock_graph(state: DebateState, decision: FinalDecision) -> MagicMock:
    graph = MagicMock()
    graph.run = AsyncMock(return_value=(state, decision))
    return graph


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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_metrics():
    app_metrics.reset()
    yield
    app_metrics.reset()


@pytest.fixture
def isolated_stores():
    debate_store: dict[str, DebateState] = {}
    decision_store: dict[str, FinalDecision] = {}

    app.dependency_overrides[get_debate_store] = lambda: debate_store
    app.dependency_overrides[get_decision_store] = lambda: decision_store

    yield debate_store, decision_store

    app.dependency_overrides.pop(get_debate_store, None)
    app.dependency_overrides.pop(get_decision_store, None)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestRequestCorrelation:

    @pytest.mark.anyio
    async def test_echoes_client_request_id(self, client):
        response = await client.get("/health", headers={"X-Request-ID": "req-123"})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "req-123"

    @pytest.mark.anyio
    async def test_request_completion_log_contains_request_id(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="agentboard"):
            response = await client.get("/health", headers={"X-Request-ID": "req-456"})

        assert response.status_code == 200
        access_log = next(
            record for record in caplog.records if record.getMessage() == "http_request_completed"
        )
        assert access_log.request_id == "req-456"
        assert access_log.status_code == 200
        assert access_log.path == "/health"


class TestStructuredLogging:

    def test_json_formatter_serializes_extra_fields(self):
        formatter = JSONFormatter()
        logger = logging.getLogger("agentboard.test")
        token = set_request_id("req-789")
        try:
            record = logger.makeRecord(
                logger.name,
                logging.INFO,
                __file__,
                42,
                "structured_log",
                args=(),
                exc_info=None,
                extra={"thread_id": "thread-1", "status_code": 200},
            )
        finally:
            reset_request_id(token)

        payload = json.loads(formatter.format(record))

        assert payload["message"] == "structured_log"
        assert payload["request_id"] == "req-789"
        assert payload["thread_id"] == "thread-1"
        assert payload["status_code"] == 200


class TestMetricsAndAudit:

    @pytest.mark.anyio
    async def test_metrics_endpoint_reports_route_counters(self, client):
        await client.get("/health")

        response = await client.get("/metrics")

        assert response.status_code == 200
        body = response.json()
        assert body["requests_total"] == 1
        assert body["responses_by_status"]["200"] == 1
        assert body["routes"]["GET /health"]["count"] == 1

    @pytest.mark.anyio
    async def test_sync_debate_start_updates_metrics_and_emits_audit_log(
        self,
        client,
        isolated_stores,
        caplog,
    ):
        state = _make_state()
        decision = _make_decision(thread_id=state.thread_id)

        with patch("app.api.routes.DebateGraph", return_value=_mock_graph(state, decision)):
            with caplog.at_level(logging.INFO, logger="agentboard.audit"):
                response = await client.post(
                    "/debate/start",
                    json={"query": "Should we expand into the Asian market in Q3?", "max_rounds": 2},
                    headers={"X-Request-ID": "req-audit"},
                )

        assert response.status_code == 200
        metrics = app_metrics.snapshot()
        assert metrics["events"]["debate.started_sync"] == 1
        assert metrics["events"]["debate.completed_sync"] == 1

        audit_record = next(
            record
            for record in caplog.records
            if record.name == "agentboard.audit" and record.getMessage() == "audit_event"
        )
        assert audit_record.action == "debate.start"
        assert audit_record.outcome == "success"
        assert audit_record.thread_id == state.thread_id
        assert audit_record.request_id == "req-audit"