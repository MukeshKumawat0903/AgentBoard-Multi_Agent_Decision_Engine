"""
A debate needs at least two agents besides the Moderator, who only synthesises.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.schemas.api_models import DebateStartRequest, SimulateRequest

QUERY = "Should we expand into the Southeast Asian market?"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("model", [DebateStartRequest, SimulateRequest])
@pytest.mark.parametrize("agents", [["Moderator", "Analyst"], ["Moderator"], ["Analyst"], ["Analyst", "Analyst"]])
def test_fewer_than_two_debaters_is_rejected(model, agents):
    with pytest.raises(ValidationError, match="at least 2 debating agents"):
        model(query=QUERY, agents=agents)


@pytest.mark.parametrize("model", [DebateStartRequest, SimulateRequest])
@pytest.mark.parametrize(
    "agents", [["Analyst", "Risk"], ["Analyst", "Risk", "Moderator"], None, []]
)
def test_two_or_more_debaters_or_the_default_set_are_accepted(model, agents):
    assert model(query=QUERY, agents=agents).agents == agents


@pytest.mark.parametrize("model", [DebateStartRequest, SimulateRequest])
def test_a_domain_pack_replaces_the_agent_list(model):
    req = model(query=QUERY, agents=["Moderator", "Analyst"], domain_pack="finance")
    assert req.domain_pack == "finance"


@pytest.mark.anyio
async def test_api_rejects_a_moderator_plus_one_debate():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        resp = await client.post("/debate/start-async", json={"query": QUERY, "agents": ["Moderator", "Risk"]})

    assert resp.status_code == 422
    assert "at least 2 debating agents" in resp.text
