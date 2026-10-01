"""
Rate limits must be per *end user*: browsers reach the API through the Next.js
proxy, so the forwarded client address has to be used — but only when the
direct peer is a trusted proxy, and never a client-supplied left-most hop.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limiter import client_ip
from app.main import app


def _request(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 5555)})


@pytest.fixture(autouse=True)
def _trust_loopback_and_docker(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1,172.16.0.0/12")


def test_forwarded_address_used_behind_trusted_proxy():
    assert client_ip(_request("127.0.0.1", "203.0.113.7")) == "203.0.113.7"
    assert client_ip(_request("172.18.0.5", "198.51.100.2")) == "198.51.100.2"  # CIDR


def test_right_most_hop_wins_over_client_supplied_entries():
    assert client_ip(_request("127.0.0.1", "1.2.3.4, 203.0.113.7")) == "203.0.113.7"


def test_untrusted_peer_cannot_spoof_its_address():
    assert client_ip(_request("8.8.8.8", "203.0.113.7")) == "8.8.8.8"


def test_missing_or_invalid_forwarded_value_falls_back_to_peer():
    assert client_ip(_request("127.0.0.1")) == "127.0.0.1"
    assert client_ip(_request("127.0.0.1", "unknown")) == "127.0.0.1"


@pytest.mark.anyio
async def test_each_client_behind_the_proxy_gets_its_own_bucket(monkeypatch):
    """The simulation cap (2/hour) applies per client, not to everyone at once."""
    from unittest.mock import patch

    from app.services.simulation import SimulationResult

    async def fake_run_simulation(**kwargs):
        return SimulationResult(query=kwargs["query"], runs=2, runs_completed=2, decisions=[],
                                consistency_score=1.0, confidence_variance=0.0,
                                avg_agreement_score=0.8, stable_risk_flags=[], stability_rating="High")

    app.state.limiter.reset()
    body = {"query": "Should we adopt Kubernetes now?", "runs": 2}
    # httpx's ASGI transport connects from 127.0.0.1 — i.e. "the proxy".
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        with patch("app.services.simulation.run_simulation", side_effect=fake_run_simulation):
            alice = {"X-Forwarded-For": "203.0.113.10"}
            bob = {"X-Forwarded-For": "203.0.113.20"}
            assert (await client.post("/debate/simulate", json=body, headers=alice)).status_code == 200
            assert (await client.post("/debate/simulate", json=body, headers=alice)).status_code == 200
            assert (await client.post("/debate/simulate", json=body, headers=alice)).status_code == 429
            assert (await client.post("/debate/simulate", json=body, headers=bob)).status_code == 200
    app.state.limiter.reset()
