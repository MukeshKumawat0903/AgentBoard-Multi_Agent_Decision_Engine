"""
Administrative actions affect every user of a deployment (switching the global
LLM provider, clearing agent memory, deleting KB documents). They need the
admin token when one is configured, are refused in production without one,
and stay open for local development.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
SWITCH = {"provider": "openai", "model": "gpt-5.5"}


@pytest.fixture
def reset_mock():
    with patch("app.api.routes.reset_llm_client") as mock:
        yield mock


@pytest.fixture
def dev_open(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "")
    monkeypatch.setattr(settings, "APP_ENV", "development")


def test_switch_uses_the_servers_key_when_none_is_supplied(dev_open, monkeypatch, reset_mock):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "server-openai-key")
    resp = client.post("/llm-settings", json=SWITCH)

    assert resp.status_code == 200
    assert resp.json()["using_custom_key"] is False
    assert reset_mock.call_args.kwargs["api_key"] == "server-openai-key"


def test_switch_without_any_key_is_rejected_cleanly(dev_open, monkeypatch, reset_mock):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    resp = client.post("/llm-settings", json=SWITCH)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "api_key_required"
    reset_mock.assert_not_called()


def test_user_supplied_key_is_flagged_as_custom(dev_open, reset_mock):
    resp = client.post("/llm-settings", json={**SWITCH, "api_key": "sk-user"})

    assert resp.status_code == 200 and resp.json()["using_custom_key"] is True
    assert reset_mock.call_args.kwargs["api_key"] == "sk-user"


def test_configured_token_is_required(monkeypatch, reset_mock):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "s3cret-admin")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "server-openai-key")

    assert client.post("/llm-settings", json=SWITCH).status_code == 401
    assert client.post("/llm-settings", json=SWITCH, headers={"X-Admin-Token": "wrong"}).status_code == 401
    ok = client.post("/llm-settings", json=SWITCH, headers={"X-Admin-Token": "s3cret-admin"})
    assert ok.status_code == 200
    assert reset_mock.call_count == 1


def test_production_without_a_token_refuses_admin_actions(monkeypatch, reset_mock):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "")
    monkeypatch.setattr(settings, "APP_ENV", "production")

    resp = client.post("/llm-settings", json=SWITCH)
    assert resp.status_code == 403 and resp.json()["detail"]["error"] == "admin_disabled"
    reset_mock.assert_not_called()


@pytest.mark.parametrize("method,path", [
    ("delete", "/memory/Analyst"),
    ("delete", "/knowledge/documents/report.pdf"),
])
def test_destructive_endpoints_are_guarded(monkeypatch, method, path):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "s3cret-admin")
    kb = MagicMock(is_available=True)
    with patch("app.api.dependencies.get_knowledge_base", return_value=kb), \
         patch("app.api.dependencies.get_memory_store", return_value=None):
        denied = getattr(client, method)(path)
        allowed = getattr(client, method)(path, headers={"X-Admin-Token": "s3cret-admin"})
    assert denied.status_code == 401
    assert allowed.status_code != 401


def test_settings_report_server_keys_and_whether_a_token_is_needed(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "s3cret-admin")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    with patch("app.api.routes.get_active_provider_info",
               return_value={"provider": "groq", "model": "llama-3.3-70b-versatile", "using_custom_key": False}):
        body = client.get("/llm-settings").json()
    assert body["admin_token_required"] is True
    assert body["server_keys"]["groq"] is True and body["server_keys"]["openai"] is False
