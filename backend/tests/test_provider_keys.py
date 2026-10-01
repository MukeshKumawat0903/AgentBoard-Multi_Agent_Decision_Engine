"""
Every provider — including Gemini — takes its server key from one shared map,
both for the global client and for per-agent model overrides.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.analyst_agent import AnalystAgent
from app.agents.registry import AgentConfig, AgentRegistry
from app.core.config import settings
from app.services import llm_client


def _registry_with_override(provider: str, model: str) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        AnalystAgent,
        AgentConfig(
            name="Analyst", role="r", icon="x", system_prompt="",
            model_provider=provider, model_name=model,
        ),
    )
    return registry


def _default_client() -> MagicMock:
    client = MagicMock()
    client.provider, client.model = "groq", "llama-3.3-70b-versatile"
    return client


@pytest.mark.parametrize(
    ("provider", "key_setting"),
    [("gemini", "GEMINI_API_KEY"), ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")],
)
def test_agent_override_uses_that_providers_server_key(monkeypatch, provider, key_setting):
    monkeypatch.setattr(settings, key_setting, f"{provider}-key")
    registry = _registry_with_override(provider, f"{provider}-model")
    with patch("app.services.llm_client.LangChainProvider") as provider_cls:
        registry.get("Analyst", llm_client=_default_client())

    provider_cls.assert_called_once_with(provider=provider, api_key=f"{provider}-key", model=f"{provider}-model")


def test_agent_override_without_a_key_still_fails_clearly(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    registry = _registry_with_override("gemini", "gemini-3.5-flash")
    with pytest.raises(ValueError, match="no API key"):
        registry.get("Analyst", llm_client=_default_client())


@pytest.mark.parametrize("provider", ["groq", "openai", "anthropic", "gemini"])
def test_global_client_uses_the_same_key_and_model_map(monkeypatch, provider):
    monkeypatch.setattr(settings, "LLM_PROVIDER", provider)
    monkeypatch.setattr(settings, f"{provider.upper()}_API_KEY", f"{provider}-key")
    monkeypatch.setattr(llm_client, "_llm_client_instance", None)
    with patch.object(llm_client, "LangChainProvider") as provider_cls:
        llm_client.get_llm_client()

    provider_cls.assert_called_once_with(
        provider=provider, api_key=f"{provider}-key", model=getattr(settings, f"{provider.upper()}_MODEL")
    )
