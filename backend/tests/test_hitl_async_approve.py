"""
End-to-end HITL flow through the HTTP API with the real LangGraph engine and a
fake LLM: approval runs in the background (202), a second approval while one
is running is rejected, the continuation streams its own events, and a
failure during the continuation keeps the newest rounds.
"""

import asyncio

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.base_agent import AgentLLMOutput, CritiqueLLMOutput
from app.agents.moderator_agent import FinalDecisionLLMOutput, ModeratorSynthesis
from app.api.dependencies import (
    get_background_tasks,
    get_debate_store,
    get_decision_store,
    get_groq_client,
)
from app.core.config import settings
from app.db.crud import get_debate_events, get_debate_state_json
from app.main import app
from app.schemas.state import DebateState


class _GatedLLM:
    """Fake LLM; agent calls wait on ``gate`` so a run can be held mid-flight."""

    provider = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.gate.set()
        self.fail_synthesis = False
        self.fail_agents = False

    async def ainvoke_structured(self, schema, system_prompt, user_prompt, **_kwargs):
        if schema is AgentLLMOutput:
            await self.gate.wait()
            if self.fail_agents:
                raise RuntimeError("provider exploded during proposals")
            return AgentLLMOutput(position="Run a careful pilot first.", reasoning="r", confidence_score=0.9, stance="support")
        if schema is CritiqueLLMOutput:
            return CritiqueLLMOutput(critique_points=["minor"], severity="low", confidence_score=0.5)
        if schema is ModeratorSynthesis:
            if self.fail_synthesis:
                raise RuntimeError("provider exploded during synthesis")
            return ModeratorSynthesis(summary="s", agreement_score=0.9, should_continue=False)
        if schema is FinalDecisionLLMOutput:
            return FinalDecisionLLMOutput(
                decision="Proceed", rationale_summary="why", confidence_score=0.8, agreement_score=0.8
            )
        raise AssertionError(schema)


@pytest.fixture
def llm():
    fake = _GatedLLM()
    debate_store: dict = {}
    decision_store: dict = {}
    tasks: dict = {}
    app.dependency_overrides[get_groq_client] = lambda: fake
    app.dependency_overrides[get_debate_store] = lambda: debate_store
    app.dependency_overrides[get_decision_store] = lambda: decision_store
    app.dependency_overrides[get_background_tasks] = lambda: tasks
    fake.tasks = tasks
    yield fake
    for dep in (get_groq_client, get_debate_store, get_decision_store, get_background_tasks):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:  # type: ignore[arg-type]
        yield ac


async def _wait_for_status(client, thread_id: str, wanted: str, timeout: float = 20.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        body = (await client.get(f"/debate/{thread_id}")).json()
        if body.get("status") == wanted:
            return body
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"status stayed {body.get('status')!r}, wanted {wanted!r}")
        await asyncio.sleep(0.05)


async def _wait_until_idle(tasks: dict, thread_id: str, timeout: float = 20.0) -> None:
    task = tasks.get(thread_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout)


async def _event_types(thread_id: str) -> list[str]:
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        return [e["type"] for e in await get_debate_events(db, thread_id)]


async def _start_supervised(client, llm) -> str:
    resp = await client.post(
        "/debate/start-async",
        json={"query": "Which vendor should we pick for the rollout?", "mode": "quick", "supervised": True},
    )
    assert resp.status_code == 200
    thread_id = resp.json()["thread_id"]
    await _wait_until_idle(llm.tasks, thread_id)
    await _wait_for_status(client, thread_id, "awaiting_approval")
    return thread_id


@pytest.mark.anyio
async def test_add_round_then_approve_runs_in_background_and_finishes(client, llm):
    thread_id = await _start_supervised(client, llm)

    llm.gate.clear()  # hold the extra round mid-flight
    resp = await client.post(f"/debate/{thread_id}/approve", json={"action": "add_round"})
    assert resp.status_code == 202
    assert resp.json()["status"] == "resuming"

    # A second approval while the first is still running is rejected.
    dup = await client.post(f"/debate/{thread_id}/approve", json={"action": "approve"})
    assert dup.status_code == 409
    assert dup.json()["detail"]["error"] == "debate_in_progress"

    llm.gate.set()
    await _wait_until_idle(llm.tasks, thread_id)
    paused = await _wait_for_status(client, thread_id, "awaiting_approval")
    assert paused["current_round"] == 2
    # The continuation streamed its own second approval request.
    assert (await _event_types(thread_id)).count("approval_required") == 2

    resp = await client.post(f"/debate/{thread_id}/approve", json={"action": "approve"})
    assert resp.status_code == 202
    await _wait_until_idle(llm.tasks, thread_id)

    decision = await client.get(f"/decision/{thread_id}")
    assert decision.status_code == 200
    assert decision.json()["total_rounds"] == 2
    assert "final_decision" not in await _event_types(thread_id)  # sent live, not persisted
    assert "debate_completed" in await _event_types(thread_id)


@pytest.mark.anyio
async def test_approve_rejects_debate_that_is_not_paused(client, llm):
    thread_id = await _start_supervised(client, llm)
    await client.post(f"/debate/{thread_id}/approve", json={"action": "approve"})
    await _wait_until_idle(llm.tasks, thread_id)

    again = await client.post(f"/debate/{thread_id}/approve", json={"action": "approve"})
    assert again.status_code == 409
    assert again.json()["detail"]["error"] == "debate_not_awaiting_approval"


@pytest.mark.anyio
async def test_approve_unknown_debate_is_404(client, llm):
    resp = await client.post("/debate/no-such-thread/approve", json={"action": "approve"})
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_failure_during_continuation_keeps_the_newest_rounds(client, llm):
    """The continuation runs on a checkpoint copy of the state; a fatal failure
    inside the extra round must persist that newer copy (round 2), not the
    snapshot taken before the approval (round 1)."""
    thread_id = await _start_supervised(client, llm)

    # Round 2: every agent fails and so does the moderator — nothing to salvage.
    llm.fail_agents = True
    llm.fail_synthesis = True
    resp = await client.post(f"/debate/{thread_id}/approve", json={"action": "add_round"})
    assert resp.status_code == 202
    await _wait_until_idle(llm.tasks, thread_id)

    status = await _wait_for_status(client, thread_id, "error")
    assert status["current_round"] == 2
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        persisted = DebateState.model_validate_json(await get_debate_state_json(db, thread_id))
    assert persisted.status == "error"
    assert persisted.current_round == 2 and len(persisted.rounds) == 2
    assert "error" in await _event_types(thread_id)
