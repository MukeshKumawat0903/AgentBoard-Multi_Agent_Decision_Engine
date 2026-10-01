"""
Token usage / cost must cover the whole debate, including segments run after a
HITL pause; agent-memory saves must not be garbage-collected mid-flight and
must use the provider that is active when they run.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.orchestrator.debate_graph import DebateGraph
from app.services.agent_memory import AgentMemoryStore

SEGMENT = {"llama-3.3-70b-versatile": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}}


def test_merge_usage_sums_counters_per_model_and_ignores_non_ints():
    merged = DebateGraph._merge_usage(
        {"m1": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6, "input_token_details": {"x": 1}}},
        {"m1": {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4}, "m2": {"input_tokens": 7}},
        None,
    )
    assert merged == {
        "m1": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        "m2": {"input_tokens": 7},
    }


@pytest.mark.anyio
async def test_cost_after_hitl_approval_covers_both_segments():
    from app.api.dependencies import get_background_tasks, get_groq_client
    from app.main import app
    from tests.test_hitl_async_approve import _GatedLLM, _start_supervised, _wait_until_idle

    real = DebateGraph._ainvoke_with_usage

    async def with_fixed_usage(self, graph, graph_input, config):
        result, _ = await real(self, graph, graph_input, config)
        return result, SEGMENT

    llm, tasks = _GatedLLM(), {}
    llm.tasks = tasks
    app.dependency_overrides[get_groq_client] = lambda: llm
    app.dependency_overrides[get_background_tasks] = lambda: tasks
    try:
        with patch.object(DebateGraph, "_ainvoke_with_usage", with_fixed_usage):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
                thread_id = await _start_supervised(client, llm)        # segment 1 → pause
                await client.post(f"/debate/{thread_id}/approve", json={"action": "approve"})
                await _wait_until_idle(tasks, thread_id)               # segment 2 → decision
                decision = (await client.get(f"/decision/{thread_id}")).json()
    finally:
        app.dependency_overrides.pop(get_groq_client, None)
        app.dependency_overrides.pop(get_background_tasks, None)

    assert decision["token_usage"]["input_tokens"] == 200
    assert decision["token_usage"]["output_tokens"] == 20
    assert decision["token_usage"]["total_tokens"] == 220
    assert decision["estimated_cost_usd"] is not None


def test_memory_store_uses_the_provider_active_when_saving():
    store = AgentMemoryStore(database_url=":memory:")
    first, second = MagicMock(name="first"), MagicMock(name="second")
    with patch("app.services.llm_client.get_llm_client", return_value=first):
        assert store.llm_client is first
    with patch("app.services.llm_client.get_llm_client", return_value=second):
        assert store.llm_client is second
    pinned = AgentMemoryStore(database_url=":memory:", llm_client=first)
    assert pinned.llm_client is first


@pytest.mark.anyio
async def test_memory_save_tasks_are_held_until_they_finish():
    import app.orchestrator.nodes as nodes
    from app.schemas.agent_response import AgentResponse
    from app.schemas.final_decision import FinalDecision
    from app.schemas.state import DebateRound, DebateState

    gate = asyncio.Event()

    async def slow_save(*_args):
        await gate.wait()

    memory = MagicMock()
    memory.save_memory = slow_save
    moderator = MagicMock()
    ds = DebateState(
        user_query="Which vendor should we pick?", current_round=1, enable_agent_memory=True,
        rounds=[DebateRound(round_number=1, agent_outputs=[
            AgentResponse(agent_name=n, round_number=1, position="p", reasoning="r", confidence_score=0.8)
            for n in ("Analyst", "Risk")
        ])],
    )
    moderator.finalize = AsyncMock(return_value=FinalDecision(
        thread_id=ds.thread_id, decision="Proceed", rationale_summary="why", confidence_score=0.8,
        agreement_score=0.7, total_rounds=1, termination_reason="consensus_reached"))
    node = nodes.make_finalize_node(moderator, MagicMock(), None, memory, None, ["Analyst", "Risk"])

    await node({"debate_state": ds, "should_continue": False, "final_decision": None})
    pending = set(nodes._memory_tasks)
    assert len(pending) == 2  # strongly referenced while running

    gate.set()
    await asyncio.gather(*pending)
    await asyncio.sleep(0)
    assert not (pending & nodes._memory_tasks)  # released once done
