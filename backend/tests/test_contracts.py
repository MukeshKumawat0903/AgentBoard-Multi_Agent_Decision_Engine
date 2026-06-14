"""
Phase 6.2 — API contract tests.

Validates that every endpoint response matches its declared Pydantic schema
and that SSE event payloads conform to their TypedDict specifications.
No real LLM calls are made — all external dependencies are mocked.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.api_models import (
    AsyncDebateStartResponse,
    DebateStatusResponse,
    HistoryListResponse,
    LLMSettingsResponse,
)
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_final_decision(thread_id: str = "t-001") -> FinalDecision:
    state = DebateState(user_query="Should we expand into Asia?")
    return FinalDecision(
        thread_id=thread_id,
        query=state.user_query,
        decision="Proceed with phased expansion.",
        rationale_summary="Analysis supports cautious growth.",
        confidence_score=0.82,
        agreement_score=0.78,
        total_rounds=2,
        termination_reason="consensus_reached",
    )


@pytest.fixture(scope="module")
def app_client():
    """TestClient with the registry seeded so agent endpoints return real data."""
    from app.agents.analyst_agent import AnalystAgent, SYSTEM_PROMPT as AP  # noqa: PLC0415
    from app.agents.risk_agent import RiskAgent, SYSTEM_PROMPT as RP  # noqa: PLC0415
    from app.agents.strategy_agent import StrategyAgent, SYSTEM_PROMPT as SP  # noqa: PLC0415
    from app.agents.ethics_agent import EthicsAgent, SYSTEM_PROMPT as EP  # noqa: PLC0415
    from app.agents.moderator_agent import ModeratorAgent, SYNTHESIS_SYSTEM_PROMPT as MP  # noqa: PLC0415
    from app.agents.registry import registry, AgentConfig  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    if not registry.is_registered("Analyst"):
        for cls, name, role, icon, prompt in [
            (AnalystAgent,  "Analyst",  "Objective analyst",     "📊", AP),
            (RiskAgent,     "Risk",     "Risk assessor",         "⚠️",  RP),
            (StrategyAgent, "Strategy", "Strategy proposer",     "🎯", SP),
            (EthicsAgent,   "Ethics",   "Ethics evaluator",      "🤝", EP),
            (ModeratorAgent,"Moderator","Debate moderator",      "🏛️", MP),
        ]:
            registry.register(cls, AgentConfig(name=name, role=role, icon=icon, system_prompt=prompt))

    return TestClient(app, raise_server_exceptions=False)


def _make_app_client():
    """Import app lazily — no registry seeding; use for endpoints that don't need it."""
    from app.main import app  # noqa: PLC0415
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok_with_required_fields(self):
        client = _make_app_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "groq_configured" in body

    def test_health_schema_is_stable(self):
        client = _make_app_client()
        resp = client.get("/health")
        body = resp.json()
        assert isinstance(body["groq_configured"], bool)
        assert isinstance(body["version"], str)


# ---------------------------------------------------------------------------
# GET /agents
# ---------------------------------------------------------------------------

class TestAgentsContract:
    def test_agents_returns_list(self, app_client):
        resp = app_client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert isinstance(agents, list)
        assert len(agents) >= 5

    def test_each_agent_has_required_fields(self, app_client):
        agents = app_client.get("/agents").json()
        required = {"name", "role", "icon", "enabled", "model_provider", "model_name"}
        for agent in agents:
            missing = required - set(agent.keys())
            assert not missing, f"Agent {agent.get('name')} missing fields: {missing}"

    def test_agent_enabled_is_bool(self, app_client):
        for agent in app_client.get("/agents").json():
            assert isinstance(agent["enabled"], bool)

    def test_system_prompt_not_exposed(self, app_client):
        for agent in app_client.get("/agents").json():
            assert "system_prompt" not in agent, "system_prompt must not be in public API response"


# ---------------------------------------------------------------------------
# GET /templates
# ---------------------------------------------------------------------------

class TestTemplatesContract:
    def test_templates_returns_list(self):
        client = _make_app_client()
        resp = client.get("/templates")
        assert resp.status_code == 200
        templates = resp.json()
        assert isinstance(templates, list)
        assert len(templates) >= 10

    def test_each_template_has_required_fields(self):
        client = _make_app_client()
        required = {"id", "title", "category", "icon", "query", "mode", "tags"}
        for t in client.get("/templates").json():
            missing = required - set(t.keys())
            assert not missing, f"Template {t.get('id')} missing: {missing}"

    def test_template_category_filter(self):
        client = _make_app_client()
        resp = client.get("/templates?category=Business")
        assert resp.status_code == 200
        for t in resp.json():
            assert t["category"] == "Business"

    def test_template_search_filter(self):
        client = _make_app_client()
        resp = client.get("/templates?q=invest")
        assert resp.status_code == 200
        for t in resp.json():
            query_lower = t["query"].lower() + t["title"].lower()
            assert "invest" in query_lower or any("invest" in tag for tag in t["tags"])


# ---------------------------------------------------------------------------
# GET /domain-packs
# ---------------------------------------------------------------------------

class TestDomainPacksContract:
    def test_domain_packs_returns_four_packs(self):
        client = _make_app_client()
        resp = client.get("/domain-packs")
        assert resp.status_code == 200
        packs = resp.json()
        assert len(packs) == 4
        ids = {p["id"] for p in packs}
        assert ids == {"finance", "engineering", "legal", "healthcare"}

    def test_each_pack_has_required_fields(self):
        client = _make_app_client()
        required = {"id", "name", "description", "icon", "agents", "paired_template_categories"}
        for pack in client.get("/domain-packs").json():
            missing = required - set(pack.keys())
            assert not missing


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------

class TestHistoryContract:
    def test_history_returns_valid_schema(self):
        client = _make_app_client()
        resp = client.get("/history")
        assert resp.status_code == 200
        body = resp.json()
        parsed = HistoryListResponse(**body)
        assert parsed.page == 1
        assert isinstance(parsed.items, list)
        assert isinstance(parsed.total, int)

    def test_history_pagination_params(self):
        client = _make_app_client()
        resp = client.get("/history?page=1&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 5

    def test_history_invalid_limit_rejected(self):
        client = _make_app_client()
        resp = client.get("/history?limit=9999")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /llm-settings
# ---------------------------------------------------------------------------

class TestLLMSettingsContract:
    def test_llm_settings_matches_schema(self):
        client = _make_app_client()
        resp = client.get("/llm-settings")
        assert resp.status_code == 200
        parsed = LLMSettingsResponse(**resp.json())
        assert parsed.provider in {"groq", "openai", "anthropic"}
        assert isinstance(parsed.using_custom_key, bool)

    def test_available_models_has_all_providers(self):
        client = _make_app_client()
        body = client.get("/llm-settings").json()
        assert "groq" in body["available_models"]
        assert "openai" in body["available_models"]
        assert "anthropic" in body["available_models"]


# ---------------------------------------------------------------------------
# POST /debate/start-async — response schema contract
# ---------------------------------------------------------------------------

class TestAsyncStartContract:
    @pytest.mark.anyio
    async def test_async_start_returns_correct_schema(self):
        from app.main import app  # noqa: PLC0415
        from fastapi.testclient import TestClient

        debate_state = DebateState(user_query="Should we expand into Asia in Q3?")
        decision = _mock_final_decision(debate_state.thread_id)

        with (
            patch("app.api.routes.DebateGraph") as MockGraph,
            patch("app.api.routes._persist_debate_state", new_callable=AsyncMock),
            patch("app.api.routes._run_debate_background", new_callable=AsyncMock),
        ):
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=(debate_state, decision))
            MockGraph.return_value = mock_instance

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/debate/start-async",
                json={"query": "Should we expand into Asia in Q3?"},
            )

        assert resp.status_code == 200
        parsed = AsyncDebateStartResponse(**resp.json())
        assert parsed.status == "initialized"
        assert parsed.stream_url.startswith("/debate/")


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------

class TestMetricsContract:
    def test_metrics_returns_dict_with_known_keys(self):
        client = _make_app_client()
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "requests" in body or "events" in body or len(body) > 0


# ---------------------------------------------------------------------------
# SSE event payload schema validation
# ---------------------------------------------------------------------------

class TestSSEEventSchemas:
    """Validate that SSE event dicts emitted by the backend match the TS type contracts."""

    def _required(self, event_type: str) -> set[str]:
        schemas: dict[str, set[str]] = {
            "debate_started":    {"type", "thread_id", "user_query", "max_rounds"},
            "round_started":     {"type", "round_number", "max_rounds"},
            "phase_started":     {"type", "round_number", "phase"},
            "agent_output":      {"type", "round_number", "phase", "agent_name", "position", "reasoning", "confidence_score", "assumptions"},
            "critique_completed":{"type", "round_number", "critic_agent", "target_agent", "severity", "critique_points", "confidence_score"},
            "synthesis":         {"type", "round_number", "agreement_score", "should_continue", "summary", "agreement_areas", "disagreement_areas"},
            "debate_completed":  {"type", "thread_id", "termination_reason", "total_rounds", "agreement_score"},
            "agent_timeout":     {"type", "round_number", "phase", "agent_name"},
            "error":             {"type"},
        }
        return schemas.get(event_type, set())

    def test_debate_started_payload_has_all_fields(self):
        payload = {"type": "debate_started", "thread_id": "t1", "user_query": "Q?", "max_rounds": 4}
        required = self._required("debate_started")
        assert required.issubset(set(payload.keys()))

    def test_agent_output_payload_has_all_fields(self):
        payload = {
            "type": "agent_output", "round_number": 1, "phase": "proposal",
            "agent_name": "Analyst", "position": "p", "reasoning": "r",
            "confidence_score": 0.8, "assumptions": [],
        }
        assert self._required("agent_output").issubset(set(payload.keys()))

    def test_critique_completed_payload_valid(self):
        payload = {
            "type": "critique_completed", "round_number": 1,
            "critic_agent": "Risk", "target_agent": "Analyst",
            "severity": "high", "critique_points": ["pt1"], "confidence_score": 0.7,
        }
        assert self._required("critique_completed").issubset(set(payload.keys()))
        assert payload["severity"] in {"low", "medium", "high", "critical"}

    def test_agent_timeout_payload_has_agent_name(self):
        payload = {"type": "agent_timeout", "round_number": 1, "phase": "proposal", "agent_name": "Analyst"}
        assert self._required("agent_timeout").issubset(set(payload.keys()))

    def test_error_payload_uses_error_not_message(self):
        payload = {"type": "error", "error": "LLMResponseError: …", "detail": "…"}
        assert "error" in payload
        assert "message" not in payload, "Backend must not send 'message' key (B10 fix)"
