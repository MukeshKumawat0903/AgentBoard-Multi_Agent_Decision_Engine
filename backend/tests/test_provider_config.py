"""
Only the active provider's API key is required, and /health reports the
provider debates are actually using.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app
from app.services import llm_client


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _settings(**env) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_groq_key_is_not_needed_for_another_provider(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = _settings(LLM_PROVIDER="openai", OPENAI_API_KEY="sk-test")
    assert (s.LLM_PROVIDER, s.GROQ_API_KEY) == ("openai", "")


@pytest.mark.parametrize("provider", ["groq", "openai", "anthropic", "gemini"])
def test_the_active_providers_key_is_required(provider):
    keys = {f"{p.upper()}_API_KEY": "" for p in ("groq", "openai", "anthropic", "gemini")}
    with pytest.raises(ValidationError, match=f"{provider.upper()}_API_KEY is required"):
        _settings(LLM_PROVIDER=provider, **keys)


def test_settings_errors_do_not_echo_secrets():
    with pytest.raises(ValidationError) as exc_info:
        _settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="", GROQ_API_KEY="gsk_do_not_print_me")
    assert "gsk_do_not_print_me" not in str(exc_info.value)
    assert "gsk_" not in str(exc_info.value)


@pytest.mark.anyio
async def test_health_reports_the_active_provider_without_creating_it(monkeypatch):
    monkeypatch.setattr(llm_client, "_llm_client_instance", None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        body = (await client.get("/health")).json()

    assert body["llm"] == {
        "provider": "groq",
        "model": llm_client.settings.GROQ_MODEL,
        "configured": True,  # conftest sets a dummy GROQ_API_KEY
    }
    assert body["groq_configured"] is True
    assert llm_client._llm_client_instance is None


@pytest.mark.anyio
async def test_health_follows_a_runtime_provider_switch(monkeypatch):
    monkeypatch.setattr(llm_client, "_llm_client_instance", None)
    monkeypatch.setattr(llm_client, "_using_custom_key", False)
    monkeypatch.setattr(llm_client, "_active_key_configured", False)
    monkeypatch.setattr(llm_client, "LangChainProvider", _FakeProvider)
    llm_client.reset_llm_client(provider="openai", api_key="sk-user", model="gpt-5.5", custom_key=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        body = (await client.get("/health")).json()

    assert body["llm"] == {"provider": "openai", "model": "gpt-5.5", "configured": True}


class _FakeProvider:
    def __init__(self, provider: str, api_key: str, model: str) -> None:
        self.provider, self.model = provider, model
