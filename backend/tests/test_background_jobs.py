"""
Long-running work runs in the background instead of holding an HTTP request
open past proxy timeouts: resuming a failed debate, cancelling a debate that
is paused for review, and scenario-simulation jobs.
"""

import asyncio
from unittest.mock import patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

import app.api.routes as routes
from app.api.dependencies import (
    get_background_tasks,
    get_debate_store,
    get_decision_store,
    get_event_queues,
    get_groq_client,
    get_simulation_jobs,
)
from app.core.config import settings
from app.db.crud import get_debate_events, get_debate_state_json, save_debate_event
from app.main import app
from app.schemas.state import DebateState
from app.services.simulation import SimulationResult
from tests.test_hitl_async_approve import _GatedLLM, _wait_for_status, _wait_until_idle


@pytest.fixture
def env():
    fake = _GatedLLM()
    stores = {"debate": {}, "decision": {}, "tasks": {}, "queues": {}, "jobs": {}}
    app.dependency_overrides[get_groq_client] = lambda: fake
    app.dependency_overrides[get_debate_store] = lambda: stores["debate"]
    app.dependency_overrides[get_decision_store] = lambda: stores["decision"]
    app.dependency_overrides[get_background_tasks] = lambda: stores["tasks"]
    app.dependency_overrides[get_event_queues] = lambda: stores["queues"]
    app.dependency_overrides[get_simulation_jobs] = lambda: stores["jobs"]
    app.state.limiter.reset()
    yield fake, stores
    for dep in (get_groq_client, get_debate_store, get_decision_store, get_background_tasks,
                get_event_queues, get_simulation_jobs):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:  # type: ignore[arg-type]
        yield ac


async def _events(thread_id: str) -> list[str]:
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        return [e["type"] for e in await get_debate_events(db, thread_id)]


# ---------------------------------------------------------------------------
# resume-async
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_failed_debate_resumes_in_the_background_and_finishes(client, env):
    llm, stores = env
    llm.fail_agents = llm.fail_synthesis = True  # round 1 fails → debate errors out
    started = await client.post(
        "/debate/start-async", json={"query": "Which vendor should we pick for the rollout?", "mode": "quick"}
    )
    thread_id = started.json()["thread_id"]
    await _wait_until_idle(stores["tasks"], thread_id)
    await _wait_for_status(client, thread_id, "error")

    llm.fail_agents = llm.fail_synthesis = False
    resp = await client.post(f"/debate/{thread_id}/resume-async")
    assert resp.status_code == 202 and resp.json()["status"] == "resuming"
    await _wait_until_idle(stores["tasks"], thread_id)

    assert (await client.get(f"/decision/{thread_id}")).status_code == 200
    events = await _events(thread_id)
    assert events.index("debate_resumed") > events.index("error")


@pytest.mark.anyio
async def test_resume_async_rejections(client, env):
    _, stores = env
    no_ckpt = DebateState(user_query="Which vendor should we pick?", status="error")
    paused = DebateState(user_query="Which vendor should we pick?", status="awaiting_approval")
    stores["debate"].update({no_ckpt.thread_id: no_ckpt, paused.thread_id: paused})

    assert (await client.post("/debate/unknown/resume-async")).status_code == 404
    resp = await client.post(f"/debate/{no_ckpt.thread_id}/resume-async")
    assert resp.status_code == 400 and resp.json()["detail"]["error"] == "no_checkpoint_available"

    with patch("app.orchestrator.debate_graph.DebateGraph.has_checkpoint", return_value=True):
        resp = await client.post(f"/debate/{paused.thread_id}/resume-async")
    assert resp.status_code == 409 and resp.json()["detail"]["error"] == "debate_awaiting_approval"


@pytest.mark.anyio
async def test_stream_of_a_resumed_debate_ignores_the_old_terminal_frame(monkeypatch):
    """History holds [error, debate_resumed, ...]: the stream must stay open for the
    new run instead of ending on the stale error."""
    from tests.test_sse_ping import _drain, _open_stream

    monkeypatch.setattr(routes, "_SSE_KEEPALIVE_SECONDS", 0.05)
    running = DebateState(user_query="Which vendor should we pick?", status="in_progress")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        for payload in ({"type": "error", "detail": "old failure"},
                        {"type": "debate_resumed", "thread_id": running.thread_id},
                        {"type": "round_started", "round_number": 2, "max_rounds": 2}):
            await save_debate_event(db, running.thread_id, payload)
        never_done = asyncio.get_running_loop().create_future()
        frames = await _drain(
            await _open_stream(db, running, {}, background_tasks={running.thread_id: never_done}),
            limit=4,
        )
        never_done.cancel()

    assert [f.split("\n")[1] for f in frames[:3]] == ["event: error", "event: debate_resumed", "event: round_started"]
    assert frames[3] == "event: ping\ndata: {}\n\n"  # still live


# ---------------------------------------------------------------------------
# cancelling a debate that is paused for review
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_paused_debate_can_be_cancelled(client, env):
    _, stores = env
    paused = DebateState(user_query="Which vendor should we pick?", status="awaiting_approval")
    stores["debate"][paused.thread_id] = paused
    subscriber: asyncio.Queue = asyncio.Queue()
    stores["queues"][paused.thread_id] = [subscriber]

    resp = await client.post(f"/debate/{paused.thread_id}/cancel")

    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert subscriber.get_nowait()["type"] == "cancelled"
    assert subscriber.get_nowait() is None  # stream closed
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        persisted = DebateState.model_validate_json(await get_debate_state_json(db, paused.thread_id))
    assert persisted.status == "cancelled"
    assert "cancelled" in await _events(paused.thread_id)
    assert paused.thread_id not in stores["queues"]


# ---------------------------------------------------------------------------
# simulation jobs
# ---------------------------------------------------------------------------

def _result(query: str) -> SimulationResult:
    return SimulationResult(
        query=query, runs=2, runs_completed=2, decisions=[], consistency_score=0.5,
        confidence_variance=0.0, avg_agreement_score=0.7, stable_risk_flags=[], stability_rating="Medium",
    )


async def _poll(client, job_id: str, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        body = (await client.get(f"/debate/simulate/{job_id}")).json()
        if body["status"] != "running" or asyncio.get_running_loop().time() > deadline:
            return body
        await asyncio.sleep(0.02)


@pytest.mark.anyio
async def test_simulation_job_completes_and_returns_its_result(client, env):
    async def fake_run_simulation(**kwargs):
        await asyncio.sleep(0.05)
        return _result(kwargs["query"])

    with patch("app.services.simulation.run_simulation", side_effect=fake_run_simulation):
        resp = await client.post("/debate/simulate-async", json={"query": "Should we adopt Kubernetes now?", "runs": 2})
        assert resp.status_code == 202 and resp.json()["status"] == "running"
        done = await _poll(client, resp.json()["job_id"])

    assert done["status"] == "completed"
    assert done["result"]["stability_rating"] == "Medium"


@pytest.mark.anyio
async def test_simulation_job_failure_is_reported_safely(client, env):
    async def failing(**_kwargs):
        raise RuntimeError("provider exploded: org_secret_123")

    with patch("app.services.simulation.run_simulation", side_effect=failing):
        resp = await client.post("/debate/simulate-async", json={"query": "Should we adopt Kubernetes now?", "runs": 2})
        done = await _poll(client, resp.json()["job_id"])

    assert done["status"] == "failed"
    assert "org_secret" not in done["error"]


@pytest.mark.anyio
async def test_simulation_job_can_be_cancelled(client, env):
    async def slow(**kwargs):
        await asyncio.sleep(60)
        return _result(kwargs["query"])

    with patch("app.services.simulation.run_simulation", side_effect=slow):
        resp = await client.post("/debate/simulate-async", json={"query": "Should we adopt Kubernetes now?", "runs": 2})
        job_id = resp.json()["job_id"]
        cancelled = await client.post(f"/debate/simulate/{job_id}/cancel")

    assert cancelled.json()["status"] == "cancelled"
    assert (await client.get("/debate/simulate/missing")).status_code == 404
