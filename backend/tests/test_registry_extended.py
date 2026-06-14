"""
Phase 6.4 — Extended AgentRegistry tests.
Covers: register/get/enable/disable, unknown agent, per-agent temperature/max_retries (B7),
model-override routing, and tool validation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import BaseAgent
from app.agents.registry import AgentConfig, AgentRegistry
from app.services.llm_client import LangChainProvider


def _mock_client() -> LangChainProvider:
    c = MagicMock(spec=LangChainProvider)
    c.provider = "groq"
    c.model = "llama-3.3-70b-versatile"
    return c


def _fresh_registry() -> AgentRegistry:
    r = AgentRegistry()
    r.register(
        AnalystAgent,
        AgentConfig(
            name="Analyst",
            role="Objective analyst",
            icon="📊",
            system_prompt="You are an analyst.",
            enabled=True,
        ),
    )
    return r


# ---------------------------------------------------------------------------
# Register / introspect
# ---------------------------------------------------------------------------

class TestRegistryBasics:
    def test_is_registered_after_register(self):
        r = _fresh_registry()
        assert r.is_registered("Analyst") is True

    def test_is_registered_false_for_unknown(self):
        r = _fresh_registry()
        assert r.is_registered("Nonexistent") is False

    def test_list_agents_returns_registered_configs(self):
        r = _fresh_registry()
        names = [cfg.name for cfg in r.list_agents()]
        assert "Analyst" in names

    def test_enabled_agents_returns_only_enabled(self):
        r = AgentRegistry()
        r.register(AnalystAgent, AgentConfig(name="A", role="r", icon="x", system_prompt="", enabled=True))
        r.register(AnalystAgent, AgentConfig(name="B", role="r", icon="x", system_prompt="", enabled=False))
        enabled = r.enabled_agents()
        assert "A" in enabled
        assert "B" not in enabled

    def test_get_config_returns_correct_config(self):
        r = _fresh_registry()
        cfg = r.get_config("Analyst")
        assert cfg.role == "Objective analyst"

    def test_get_config_raises_for_unknown(self):
        r = _fresh_registry()
        with pytest.raises(KeyError, match="Analyst2"):
            r.get_config("Analyst2")


# ---------------------------------------------------------------------------
# get() instantiation
# ---------------------------------------------------------------------------

class TestRegistryGet:
    def test_get_returns_base_agent_instance(self):
        r = _fresh_registry()
        agent = r.get("Analyst", llm_client=_mock_client())
        assert isinstance(agent, BaseAgent)

    def test_get_raises_for_unknown_agent(self):
        r = _fresh_registry()
        with pytest.raises(KeyError, match="Risk"):
            r.get("Risk", llm_client=_mock_client())

    def test_get_sets_allowed_tools(self):
        r = AgentRegistry()
        r.register(
            AnalystAgent,
            AgentConfig(name="Analyst", role="r", icon="x", system_prompt="",
                        allowed_tools=["get_current_date"]),
        )
        agent = r.get("Analyst", llm_client=_mock_client())
        assert "get_current_date" in agent.allowed_tools

    # B7 Fix verification
    def test_get_wires_temperature_from_config(self):
        r = AgentRegistry()
        r.register(
            AnalystAgent,
            AgentConfig(name="Analyst", role="r", icon="x", system_prompt="", temperature=0.7),
        )
        agent = r.get("Analyst", llm_client=_mock_client())
        assert agent.temperature == pytest.approx(0.7)

    def test_get_wires_max_retries_from_config(self):
        r = AgentRegistry()
        r.register(
            AnalystAgent,
            AgentConfig(name="Analyst", role="r", icon="x", system_prompt="", max_retries=5),
        )
        agent = r.get("Analyst", llm_client=_mock_client())
        assert agent.max_retries == 5

    def test_default_temperature_is_0_3(self):
        r = _fresh_registry()
        agent = r.get("Analyst", llm_client=_mock_client())
        assert agent.temperature == pytest.approx(0.3)

    def test_default_max_retries_is_2(self):
        r = _fresh_registry()
        agent = r.get("Analyst", llm_client=_mock_client())
        assert agent.max_retries == 2


# ---------------------------------------------------------------------------
# Tool validation
# ---------------------------------------------------------------------------

class TestToolValidation:
    def test_register_with_invalid_tool_raises(self):
        r = AgentRegistry()
        with pytest.raises(ValueError, match="nonexistent_tool"):
            r.register(
                AnalystAgent,
                AgentConfig(name="Analyst", role="r", icon="x", system_prompt="",
                            allowed_tools=["nonexistent_tool"]),
            )

    def test_register_with_valid_tool_succeeds(self):
        r = AgentRegistry()
        r.register(
            AnalystAgent,
            AgentConfig(name="Analyst", role="r", icon="x", system_prompt="",
                        allowed_tools=["get_current_date"]),
        )
        assert r.is_registered("Analyst")


# ---------------------------------------------------------------------------
# Per-agent model routing (B7)
# ---------------------------------------------------------------------------

class TestModelOverrideRouting:
    def test_no_override_returns_shared_client(self):
        r = _fresh_registry()
        client = _mock_client()
        agent = r.get("Analyst", llm_client=client)
        assert agent.llm_client is client

    def test_model_override_missing_api_key_raises(self):
        r = AgentRegistry()
        r.register(
            AnalystAgent,
            AgentConfig(
                name="Analyst", role="r", icon="x", system_prompt="",
                model_provider="openai", model_name="gpt-4o",
            ),
        )
        from unittest.mock import patch, MagicMock
        # settings is imported lazily inside _resolve_client — patch it at the source module
        mock_settings = MagicMock()
        mock_settings.GROQ_API_KEY = ""
        mock_settings.OPENAI_API_KEY = ""
        mock_settings.ANTHROPIC_API_KEY = ""
        with patch("app.core.config.settings", mock_settings):
            with pytest.raises(ValueError, match="no API key"):
                r.get("Analyst", llm_client=_mock_client())
