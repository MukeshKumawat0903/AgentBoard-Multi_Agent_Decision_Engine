"""
DEFAULT_DEBATE_MODE picks the mode used when a request doesn't choose one (and
the mode the UI pre-selects). Not set → Quick, the cheapest preset.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.main import app
from app.schemas.api_models import DebateStartRequest, SimulateRequest, resolve_debate_config

QUERY = "Should we expand internationally in Q3?"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _settings(**env) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_quick_when_not_configured(monkeypatch):
    monkeypatch.delenv("DEFAULT_DEBATE_MODE", raising=False)
    assert _settings().DEFAULT_DEBATE_MODE == "quick"


def test_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DEFAULT_DEBATE_MODE", "thorough")
    assert _settings().DEFAULT_DEBATE_MODE == "thorough"


@pytest.mark.parametrize("value", ["custom", "fast", "Standard"])
def test_unknown_modes_are_rejected(monkeypatch, value):
    monkeypatch.setenv("DEFAULT_DEBATE_MODE", value)
    with pytest.raises(ValidationError, match="DEFAULT_DEBATE_MODE"):
        _settings()


def test_requests_without_a_mode_use_the_configured_default(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_DEBATE_MODE", "standard")

    req = DebateStartRequest(query=QUERY)
    assert (req.mode, req.min_rounds, req.consensus_threshold, req.skip_critique_phase) == ("standard", 2, 0.75, False)
    assert SimulateRequest(query=QUERY).mode == "standard"
    assert resolve_debate_config(None, None, None, None) == (2, 0.75, False, 2)


def test_an_explicit_mode_beats_the_configured_default(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_DEBATE_MODE", "thorough")
    assert DebateStartRequest(query=QUERY, mode="quick").mode == "quick"
    assert SimulateRequest(query=QUERY, mode="quick").mode == "quick"


@pytest.mark.anyio
@pytest.mark.parametrize("configured", ["quick", "thorough"])
async def test_debate_modes_endpoint_reports_the_default(monkeypatch, configured):
    monkeypatch.setattr(settings, "DEFAULT_DEBATE_MODE", configured)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        resp = await client.get("/debate-modes")

    assert resp.status_code == 200
    body = resp.json()
    assert body["default_mode"] == configured
    assert body["presets"]["quick"] == {
        "max_rounds": 2, "consensus_threshold": 0.60, "skip_critique_phase": True, "min_rounds": 1,
    }
    assert set(body["presets"]) == {"quick", "standard", "thorough", "custom"}


@pytest.mark.anyio
@pytest.mark.parametrize(("flag", "installed", "expected"), [
    (False, True, False),
    (True, False, False),
    (True, True, True),
])
async def test_debate_modes_endpoint_reports_semantic_availability(monkeypatch, flag, installed, expected):
    import app.services.consensus as consensus

    monkeypatch.setattr(settings, "SEMANTIC_CONSENSUS_ENABLED", flag)
    monkeypatch.setattr(consensus, "_SEMANTIC_AVAILABLE", installed)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        resp = await client.get("/debate-modes")

    assert resp.json()["semantic_available"] is expected
