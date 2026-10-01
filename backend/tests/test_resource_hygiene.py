"""
Long-running processes must not grow without bound: in-memory caches evict
finished debates, checkpoints of finished debates are deleted (failed or
paused ones are kept so they can still be resumed), and simulation runs leave
no checkpoints behind.
"""

import sqlite3
from unittest.mock import patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import BoundedStore
from app.core.config import settings
from app.db.crud import save_decision, upsert_debate
from app.orchestrator.debate_graph import DebateGraph, prune_finished_checkpoints
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from tests.test_hitl_override import _RecordingLLM


def _checkpoint_threads() -> set[str]:
    with sqlite3.connect(settings.CHECKPOINT_DATABASE_URL) as conn:
        return {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}


async def _run_debate(llm=None) -> DebateState:
    graph = DebateGraph(llm_client=llm or _RecordingLLM(), settings=settings)  # type: ignore[arg-type]
    state = DebateState(user_query="Which vendor should we pick for the rollout?", max_rounds=2, min_rounds=1)
    final, _ = await graph.run(state.user_query, initial_state=state)
    return final


# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

def _state(status: str) -> DebateState:
    return DebateState(user_query="Which vendor should we pick?", status=status)


def test_bounded_store_evicts_oldest_finished_entries_only():
    store = BoundedStore(2, lambda s: s.status in {"converged", "error"})
    running = _state("in_progress")
    store["run"] = running
    store["a"] = _state("converged")
    store["b"] = _state("error")
    store["c"] = _state("converged")

    assert list(store) == ["run", "c"]  # running kept; oldest finished dropped
    assert store["run"] is running


def test_bounded_store_may_exceed_capacity_rather_than_drop_live_debates():
    store = BoundedStore(1, lambda s: s.status == "converged")
    store["x"] = _state("in_progress")
    store["y"] = _state("awaiting_approval")
    assert set(store) == {"x", "y"}


@pytest.mark.anyio
async def test_evicted_decision_is_served_from_the_database():
    from app.api.dependencies import get_decision_store
    from app.main import app

    decision = FinalDecision(thread_id="evicted-1", decision="Proceed", rationale_summary="why",
                             confidence_score=0.8, agreement_score=0.7, total_rounds=1,
                             termination_reason="consensus_reached")
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await save_decision(db, decision, "Should we expand?")
    tiny = BoundedStore(1, lambda _d: True)
    app.dependency_overrides[get_decision_store] = lambda: tiny
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
            tiny["other"] = decision.model_copy(update={"thread_id": "other"})
            resp = await client.get("/decision/evicted-1")
    finally:
        app.dependency_overrides.pop(get_decision_store, None)
    assert resp.status_code == 200 and resp.json()["thread_id"] == "evicted-1"
    assert len(tiny) == 1


@pytest.mark.anyio
async def test_knowledge_base_retrieve_cache_is_bounded(tmp_path, monkeypatch):
    import app.services.retriever as retriever

    monkeypatch.setattr(retriever, "_RETRIEVE_CACHE_SIZE", 2)
    kb = retriever.KnowledgeBase(persist_dir=str(tmp_path))
    kb._available = True
    with patch.object(kb, "_retrieve_sync", return_value=[]):
        for query in ("first", "second", "third"):
            await kb.retrieve(query)
    assert [q for q, _k in kb._retrieve_cache] == ["second", "third"]


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_startup_prune_keeps_only_resumable_debates():
    finished = await _run_debate()
    failed = await _run_debate()
    await _run_debate()   # an orphan, e.g. a simulation run: no debates row
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        await upsert_debate(db, finished)
        await save_decision(db, FinalDecision(
            thread_id=finished.thread_id, decision="Proceed", rationale_summary="why",
            confidence_score=0.8, agreement_score=0.7, total_rounds=1,
            termination_reason="consensus_reached"), finished.user_query)
        failed.status = "error"
        await upsert_debate(db, failed)

    removed = await prune_finished_checkpoints(settings.CHECKPOINT_DATABASE_URL, settings.DATABASE_URL)

    assert removed == 2
    assert _checkpoint_threads() == {failed.thread_id}


@pytest.mark.anyio
async def test_completed_async_debate_drops_its_checkpoints_but_failed_one_keeps_them():
    from app.api.dependencies import get_background_tasks, get_groq_client
    from app.main import app
    from tests.test_hitl_async_approve import _GatedLLM, _wait_until_idle

    llm, tasks = _GatedLLM(), {}
    app.dependency_overrides[get_groq_client] = lambda: llm
    app.dependency_overrides[get_background_tasks] = lambda: tasks
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
            ok = (await client.post("/debate/start-async", json={
                "query": "Which vendor should we pick for the rollout?", "mode": "quick"})).json()["thread_id"]
            await _wait_until_idle(tasks, ok)
            llm.fail_agents = llm.fail_synthesis = True
            bad = (await client.post("/debate/start-async", json={
                "query": "Which vendor should we pick for the rollout?", "mode": "quick"})).json()["thread_id"]
            await _wait_until_idle(tasks, bad)
    finally:
        app.dependency_overrides.pop(get_groq_client, None)
        app.dependency_overrides.pop(get_background_tasks, None)

    threads = _checkpoint_threads()
    assert ok not in threads      # decision stored → checkpoints dropped
    assert bad in threads         # failed → still resumable


@pytest.mark.anyio
async def test_simulation_runs_leave_no_checkpoints():
    from app.services.simulation import run_simulation

    result = await run_simulation(
        query="Should we adopt Kubernetes this quarter?", runs=2, max_rounds=2, mode="quick",
        llm_client=_RecordingLLM(), settings=settings,  # type: ignore[arg-type]
    )
    assert result.runs_completed == 2
    assert _checkpoint_threads() == set()


@pytest.mark.anyio
async def test_concurrent_debates_on_a_fresh_checkpoint_db_do_not_lock(tmp_path, monkeypatch):
    """Parallel first-time setups of a new checkpoint file used to fail with
    "database is locked" (seen in simulations and right after a fresh deploy)."""
    import asyncio

    failures = 0
    for attempt in range(5):
        monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_URL", str(tmp_path / f"fresh_{attempt}.db"))
        results = await asyncio.gather(*(_run_debate() for _ in range(4)), return_exceptions=True)
        failures += sum(isinstance(r, Exception) for r in results)
    assert failures == 0
