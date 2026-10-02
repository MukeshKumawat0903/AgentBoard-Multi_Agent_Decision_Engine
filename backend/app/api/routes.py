"""
API route definitions for AgentBoard.

All REST endpoints are defined here and included
via the main FastAPI application router.
"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any, Literal

import aiosqlite
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.registry import registry
from app.api.analytics import invalidate_analytics_cache
from app.api.dependencies import (
    get_active_runs,
    get_background_tasks,
    get_db,
    get_debate_store,
    get_decision_store,
    get_event_queues,
    get_event_replays,
    get_groq_client,
    get_settings,
    get_simulation_jobs,
    get_thread_lock,
    release_thread_lock,
)
from app.core.audit import audit_event
from app.core.config import Settings
from app.core.config import settings as app_settings
from app.core.metrics import app_metrics
from app.core.rate_limiter import limiter
from app.core.security import admin_token_required, require_admin
from app.data.templates import TEMPLATES
from app.db.crud import (
    get_debate_events,
    get_debate_state_json,
    get_decision_json,
    get_evaluation_json,
    get_history,
    save_debate_event,
    save_decision,
    save_evaluation,
    upsert_debate,
)
from app.orchestrator.debate_graph import DebateGraph, require_decision
from app.schemas.api_models import (
    PROVIDER_MODELS,
    ApproveRequest,
    AsyncDebateStartResponse,
    DebateModesResponse,
    DebateStartRequest,
    DebateStatusResponse,
    ErrorResponse,
    HistoryItem,
    HistoryListResponse,
    LLMSettingsResponse,
    LLMSettingsUpdate,
    SimulateRequest,
    default_debate_mode,
    mode_presets,
    resolve_debate_config,
)
from app.schemas.final_decision import FinalDecision
from app.schemas.state import MAX_DEBATE_ROUNDS_LIMIT, DebateState
from app.services.consensus import semantic_available
from app.services.llm_client import (
    LangChainProvider,
    get_active_provider_info,
    reset_llm_client,
    server_api_key,
)
from app.services.retriever import KnowledgeBaseUnavailable
from app.utils.exceptions import public_error_message

router = APIRouter()
logger = logging.getLogger("agentboard.api")

# Quiet SSE connections get a `ping` event this often (seconds).
_SSE_KEEPALIVE_SECONDS = 20.0

_TERMINAL_STATUSES = frozenset({"converged", "max_rounds_reached", "cancelled", "error"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _persist_debate(state: DebateState, decision: FinalDecision, database_url: str) -> bool:
    """Persist a completed debate to the SQLite database. Returns True on success."""
    try:
        async with aiosqlite.connect(database_url) as db:
            await upsert_debate(db, state)
            await save_decision(db, decision, state.user_query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_persist_failed", extra={"error": str(exc)})
        return False
    invalidate_analytics_cache()
    return True


async def _finish_debate(
    graph: DebateGraph, state: DebateState, decision: FinalDecision, database_url: str
) -> None:
    """Persist a finished debate, then drop its LangGraph checkpoints.

    Checkpoints exist to continue a debate; once the decision is safely stored
    they only grow the checkpoint DB. If storing failed they are kept, so the
    debate can still be resumed.
    """
    if not await _persist_debate(state, decision, database_url):
        return
    try:
        await graph.delete_checkpoints(state.thread_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("checkpoint_cleanup_failed", extra={"thread_id": state.thread_id, "error": str(exc)})


async def _persist_debate_state(state: DebateState, database_url: str) -> None:
    """Persist the latest DebateState snapshot for recovery and status lookups."""
    try:
        async with aiosqlite.connect(database_url) as db:
            await upsert_debate(db, state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_state_persist_failed", extra={"error": str(exc)})


def _forget_task(background_tasks: dict[str, asyncio.Task], thread_id: str) -> Callable[[asyncio.Task], None]:
    """Done-callback that unregisters a finished task — but only if it is still the
    registered one, so it can never drop a newer run of the same debate."""
    def _done(task: asyncio.Task) -> None:
        if background_tasks.get(thread_id) is task:
            background_tasks.pop(thread_id, None)

    return _done


def _track_state_changes(
    debate_store: dict[str, DebateState], database_url: str
) -> Callable[[DebateState], Awaitable[None]]:
    """on_state_change callback that keeps the in-memory store current and persists.

    When a debate is resumed or approved, LangGraph works on a copy of the state
    loaded from its checkpoint, so the store must be updated from each node's
    snapshot; otherwise status polls and failure handling see a stale state.
    """
    async def on_state_change(state: DebateState) -> None:
        debate_store[state.thread_id] = state
        await _persist_debate_state(state, database_url)

    return on_state_change


async def _event_writer_loop(
    persist_queue: asyncio.Queue,
    queue_list: list,
    replay_buffer: list,
    thread_id: str,
    database_url: str,
) -> None:
    """Persist queued SSE payloads in emission order, then broadcast them.

    A single connection and a single in-order queue per debate guarantees the
    persisted event_id sequence matches emission order (so reconnect replay
    is never out of order) and that every live frame carries the same
    ``_event_id`` a later replay would assign it (so a client's
    Last-Event-ID stays in sync while live events are still streaming, not
    just after a replay).
    """
    async with aiosqlite.connect(database_url) as db:
        while True:
            payload = await persist_queue.get()
            if payload is None:  # sentinel - flush complete, stop
                break
            for attempt, backoff in enumerate((0.25, 0.5, None)):
                try:
                    event_id = await save_debate_event(db, thread_id, payload)
                    payload["_event_id"] = event_id
                    break
                except sqlite3.OperationalError as exc:
                    # Another connection held the write lock past the busy
                    # timeout. Discard the half-done transaction (the insert may
                    # have succeeded before the commit failed) and try again, so
                    # the event isn't silently missing from reconnect replay.
                    await db.rollback()
                    if backoff is None or "locked" not in str(exc):
                        logger.warning(
                            "db_event_persist_failed",
                            extra={"error": str(exc), "attempts": attempt + 1},
                        )
                        break
                    await asyncio.sleep(backoff)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("db_event_persist_failed", extra={"error": str(exc)})
                    break
            replay_buffer.append(payload)
            for q in list(queue_list):  # snapshot to avoid mutation races
                q.put_nowait(payload)


async def _stop_event_writer(persist_queue: asyncio.Queue, writer_task: asyncio.Task) -> None:
    """Signal the writer to flush any queued events, then wait for it to exit."""
    persist_queue.put_nowait(None)
    try:
        await writer_task
    except Exception as exc:  # noqa: BLE001
        logger.warning("event_writer_failed", extra={"error": str(exc)})


def _resolve_active_agents(body: DebateStartRequest) -> tuple[list[str] | None, str | None]:
    """Resolve the effective per-debate agent list, applying domain pack override if present."""
    if body.domain_pack:
        from app.data.domain_packs import DOMAIN_PACKS_BY_ID

        pack = DOMAIN_PACKS_BY_ID.get(body.domain_pack)
        if pack is None:
            raise HTTPException(
                status_code=422,
                detail=ErrorResponse(
                    error="unknown_domain_pack",
                    detail=f"Unknown domain pack '{body.domain_pack}'.",
                ).model_dump(),
            )
        return list(pack.agents), pack.id

    if body.agents:
        unknown = [a for a in body.agents if not registry.is_registered(a)]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=ErrorResponse(
                    error="unknown_agents",
                    detail=f"Requested agents are not registered: {unknown}",
                ).model_dump(),
            )
        return list(body.agents), None

    return None, None


async def _load_recovered_state(
    db: aiosqlite.Connection,
    thread_id: str,
    active_runs: set[str],
) -> DebateState | None:
    """Load a DebateState snapshot and convert orphaned in-progress runs to error.

    A thread present in ``active_runs`` is a synchronous /debate/start or
    /debate/{id}/resume call still executing in this process — its
    "in_progress" status is genuine, not orphaned, so leave it untouched.
    """
    state_json = await get_debate_state_json(db, thread_id)
    if not state_json:
        return None
    state = DebateState.model_validate_json(state_json)
    if state.status == "in_progress" and thread_id not in active_runs:
        state.status = "error"
        state.termination_reason = state.termination_reason or "recovery_required_after_restart"
        state.touch()
        await upsert_debate(db, state)
    return state


@contextmanager
def _track_active_run(active_runs: set[str], thread_id: str):
    """Mark ``thread_id`` as actively running in-request for the duration of the block.

    Used by synchronous /debate/start and /debate/{id}/resume so concurrent
    status polls don't mistake their "in_progress" state for an orphaned run.
    """
    active_runs.add(thread_id)
    try:
        yield
    finally:
        active_runs.discard(thread_id)


async def _cancel_paused_debate(
    state: DebateState,
    debate_store: dict[str, DebateState],
    all_queues: dict,
    all_replays: dict,
    db: aiosqlite.Connection,
) -> None:
    """Cancel a debate that is waiting for human review (no task is running)."""
    thread_id = state.thread_id
    state.status = "cancelled"
    state.termination_reason = "user_cancelled"
    state.touch()
    debate_store[thread_id] = state
    await upsert_debate(db, state)
    payload: dict[str, Any] = {"type": "cancelled", "thread_id": thread_id, "detail": "Debate cancelled by user."}
    payload["_event_id"] = await save_debate_event(db, thread_id, dict(payload))
    for q in list(all_queues.get(thread_id, [])):
        q.put_nowait(payload)
        q.put_nowait(None)
    _cleanup_terminal_thread_state(thread_id, all_queues, all_replays)


def _cleanup_terminal_thread_state(thread_id: str, all_queues: dict, all_replays: dict) -> None:
    """Drop a finished debate's in-memory SSE replay buffer, queue list, and lock.

    Called once a debate reaches a terminal state (completed/cancelled/error).
    From here on, ``debate_events``/``decisions`` in SQLite fully cover
    reconnect replay (see BUG-14), so retaining these per-thread entries for
    the life of the process would otherwise grow without bound across debates.
    """
    all_replays.pop(thread_id, None)
    all_queues.pop(thread_id, None)
    release_thread_lock(thread_id)


async def _run_debate_background(
    graph: DebateGraph,
    debate_state: DebateState,
    debate_store: dict,
    decision_store: dict,
    all_queues: dict,
    all_replays: dict,
    database_url: str,
    persist_queue: asyncio.Queue,
    writer_task: asyncio.Task,
    consensus_threshold: float | None = None,
    skip_critique_phase: bool = False,
    hitl_mode: bool = False,
    runner: Callable[[], Awaitable[tuple[DebateState, FinalDecision | None]]] | None = None,
    completed_metric: str = "debate.completed_async",
) -> None:
    """Run the debate graph, persist results, then close all subscriber queues.

    ``runner`` lets the same lifecycle (event writer, terminal events, cleanup)
    drive a continuation such as a HITL approval; by default a fresh run starts.
    """
    thread_id = debate_state.thread_id
    should_close_streams = True
    lock = get_thread_lock(thread_id)
    try:
        if runner is not None:
            final_state, decision = await runner()
        else:
            final_state, decision = await graph.run(
                debate_state.user_query,
                initial_state=debate_state,
                consensus_threshold=consensus_threshold,
                skip_critique_phase=skip_critique_phase,
                hitl_mode=hitl_mode,
            )
        async with lock:
            debate_store[thread_id] = final_state
        if decision is None:
            if final_state.status != "awaiting_approval":
                raise RuntimeError("The debate ended without a decision.")
            should_close_streams = False
            app_metrics.increment_event("debate.awaiting_approval")
            await _persist_debate_state(final_state, database_url)
            await _stop_event_writer(persist_queue, writer_task)
            logger.info("background_debate_paused_for_approval", extra={"thread_id": thread_id})
            return

        async with lock:
            decision_store[thread_id] = decision
        app_metrics.increment_event(completed_metric)
        await _finish_debate(graph, final_state, decision, database_url)
        # Drain the writer first so every emitted event (e.g. debate_completed)
        # reaches subscribers, in order, before the final_decision frame.
        await _stop_event_writer(persist_queue, writer_task)
        final_payload = json.loads(decision.model_dump_json())
        final_payload["type"] = "final_decision"
        queue_list = all_queues.get(thread_id, [])
        for q in list(queue_list):
            q.put_nowait(final_payload)
    except asyncio.CancelledError:
        # User cancelled the debate via POST /debate/{id}/cancel.
        # CancelledError is BaseException, so it bypasses the `except Exception`
        # below — handle it explicitly, then re-raise so the task ends cancelled.
        logger.info("background_debate_cancelled", extra={"thread_id": thread_id})
        app_metrics.increment_event("debate.cancelled")
        # The latest snapshot may be a newer object than debate_state (resumed
        # runs work on a checkpoint copy) — never overwrite newer rounds.
        current = debate_store.get(thread_id) or debate_state
        current.status = "cancelled"
        current.termination_reason = "user_cancelled"
        current.touch()
        debate_store[thread_id] = current
        try:
            await _persist_debate_state(current, database_url)
        except Exception:  # noqa: BLE001
            pass
        cancelled_payload = {
            "type": "cancelled",
            "thread_id": thread_id,
            "detail": "Debate cancelled by user.",
        }
        # Route through the writer so it's persisted (for reconnect replay),
        # gets an _event_id, and is broadcast in order with everything else.
        persist_queue.put_nowait(cancelled_payload)
        await _stop_event_writer(persist_queue, writer_task)
        raise
    except Exception as exc:  # noqa: BLE001
        error_type = type(exc).__name__
        logger.error(
            "background_debate_failed",
            extra={"thread_id": thread_id, "error_type": error_type, "error": str(exc)},
        )
        app_metrics.increment_event("debate.failed_async")
        current = debate_store.get(thread_id) or debate_state
        current.status = "error"
        current.termination_reason = f"error:{error_type}"
        current.touch()
        debate_store[thread_id] = current
        # Best-effort: persist the failed state so the UI can show an error banner
        try:
            async with aiosqlite.connect(database_url) as db:
                await upsert_debate(db, current)
        except Exception:  # noqa: BLE001
            pass
        # Notify SSE subscribers that the debate failed. Routed through the
        # writer so a reconnecting client can replay the error from the DB.
        error_payload = {
            "type": "error",
            "error": "debate_execution_failed",
            "error_type": error_type,
            # The full exception is in the server log above; clients get a safe text.
            "detail": public_error_message(exc),
        }
        persist_queue.put_nowait(error_payload)
        await _stop_event_writer(persist_queue, writer_task)
    finally:
        if not writer_task.done():
            writer_task.cancel()
        if should_close_streams:
            for q in list(all_queues.get(thread_id, [])):
                q.put_nowait(None)
            _cleanup_terminal_thread_state(thread_id, all_queues, all_replays)


# ---------------------------------------------------------------------------
# POST /debate/start  –  synchronous full-debate execution (V1)
# ---------------------------------------------------------------------------

@router.post(
    "/debate/start",
    response_model=FinalDecision,
    tags=["debate"],
    summary="Start a new multi-agent debate and wait for the final decision.",
)
@limiter.limit(f"{app_settings.RATE_LIMIT_PER_MINUTE}/minute")
async def start_debate(
    request: Request,
    body: DebateStartRequest,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    active_runs: set[str] = Depends(get_active_runs),
) -> FinalDecision:
    """
    Run a complete multi-agent debate synchronously and return the
    `FinalDecision`.  The client blocks until the debate finishes.
    Rate-limited to the configured per-minute application limit.
    """
    if body.supervised:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="supervised_requires_async",
                detail="Supervised debates must be started via /debate/start-async.",
            ).model_dump(),
        )
    selected_agents, domain_pack = _resolve_active_agents(body)
    resolved_rounds, resolved_threshold, resolved_skip, resolved_min = resolve_debate_config(
        mode=body.mode,
        max_rounds=body.max_rounds,
        consensus_threshold=body.consensus_threshold,
        skip_critique_phase=body.skip_critique_phase,
        min_rounds=body.min_rounds,
    )
    from app.api.dependencies import get_knowledge_base, get_memory_store
    kb = get_knowledge_base() if body.use_knowledge_base else None
    ms = get_memory_store() if body.enable_agent_memory else None

    debate_state = DebateState(
        user_query=body.query,
        max_rounds=resolved_rounds,
        min_rounds=resolved_min,
        mode=body.mode,
        template_id=body.template_id,
        use_knowledge_base=bool(body.use_knowledge_base),
        enable_agent_memory=bool(body.enable_agent_memory),
        selected_agents=selected_agents,
        domain_pack=domain_pack,
        agreement_method=body.agreement_method or settings.AGREEMENT_METHOD,
    )
    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        on_state_change=_track_state_changes(debate_store, settings.DATABASE_URL),
        knowledge_base=kb,
        memory_store=ms,
        selected_agents=selected_agents,
    )
    logger.info("api_debate_start")
    with _track_active_run(active_runs, debate_state.thread_id):
        state, decision = await graph.run(
            body.query,
            initial_state=debate_state,
            consensus_threshold=resolved_threshold,
            skip_critique_phase=resolved_skip,
        )
        decision = require_decision(decision)
        debate_store[state.thread_id] = state
        decision_store[state.thread_id] = decision
        app_metrics.increment_event("debate.started_sync")
        app_metrics.increment_event("debate.completed_sync")
        await _finish_debate(graph, state, decision, settings.DATABASE_URL)
    logger.info(
        "api_debate_complete",
        extra={"thread_id": state.thread_id, "termination_reason": state.termination_reason},
    )
    audit_event(
        "debate.start",
        outcome="success",
        request=request,
        thread_id=state.thread_id,
        mode=body.mode,
        domain_pack=domain_pack,
        selected_agents=selected_agents,
    )
    return decision


# ---------------------------------------------------------------------------
# POST /debate/start-async  –  returns immediately; debate runs in background
# ---------------------------------------------------------------------------

@router.post(
    "/debate/start-async",
    response_model=AsyncDebateStartResponse,
    tags=["debate"],
    summary="Start a debate in the background; connect to the stream URL for live events.",
)
@limiter.limit(f"{app_settings.RATE_LIMIT_PER_MINUTE}/minute")
async def start_debate_async(
    request: Request,
    body: DebateStartRequest,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
) -> AsyncDebateStartResponse:
    selected_agents, domain_pack = _resolve_active_agents(body)
    # Pre-create state so we have a thread_id before the graph runs.
    # Create channels at the same time so no events are lost.
    resolved_rounds, resolved_threshold, resolved_skip, resolved_min = resolve_debate_config(
        mode=body.mode,
        max_rounds=body.max_rounds,
        consensus_threshold=body.consensus_threshold,
        skip_critique_phase=body.skip_critique_phase,
        min_rounds=body.min_rounds,
    )
    debate_state = DebateState(
        user_query=body.query,
        max_rounds=resolved_rounds,
        min_rounds=resolved_min,
        mode=body.mode,
        template_id=body.template_id,
        use_knowledge_base=bool(body.use_knowledge_base),
        enable_agent_memory=bool(body.enable_agent_memory),
        selected_agents=selected_agents,
        domain_pack=domain_pack,
        agreement_method=body.agreement_method or settings.AGREEMENT_METHOD,
    )
    thread_id = debate_state.thread_id
    queue_list: list = []
    replay_buffer: list = []
    persist_queue: asyncio.Queue = asyncio.Queue()
    all_queues[thread_id] = queue_list
    all_replays[thread_id] = replay_buffer
    debate_store[thread_id] = debate_state
    await _persist_debate_state(debate_state, settings.DATABASE_URL)

    from app.api.dependencies import get_knowledge_base, get_memory_store
    kb = get_knowledge_base() if body.use_knowledge_base else None
    ms = get_memory_store() if body.enable_agent_memory else None

    writer_task = asyncio.create_task(
        _event_writer_loop(persist_queue, queue_list, replay_buffer, thread_id, settings.DATABASE_URL)
    )

    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        queue_list=queue_list,
        replay_buffer=replay_buffer,
        persist_queue=persist_queue,
        on_state_change=_track_state_changes(debate_store, settings.DATABASE_URL),
        knowledge_base=kb,
        memory_store=ms,
        selected_agents=selected_agents,
    )

    logger.info("api_async_debate_start", extra={"thread_id": thread_id})
    app_metrics.increment_event("debate.started_async")
    audit_event(
        "debate.start_async",
        outcome="accepted",
        request=request,
        thread_id=thread_id,
        mode=body.mode,
        supervised=bool(body.supervised),
        domain_pack=domain_pack,
        selected_agents=selected_agents,
    )

    task = asyncio.create_task(
        _run_debate_background(
            graph, debate_state, debate_store, decision_store,
            all_queues, all_replays, settings.DATABASE_URL,
            persist_queue=persist_queue,
            writer_task=writer_task,
            consensus_threshold=resolved_threshold,
            skip_critique_phase=resolved_skip,
            hitl_mode=bool(body.supervised),
        )
    )
    background_tasks[thread_id] = task
    task.add_done_callback(_forget_task(background_tasks, thread_id))
    return AsyncDebateStartResponse(
        thread_id=thread_id,
        status="initialized",
        stream_url=f"/debate/{thread_id}/stream",
    )


# ---------------------------------------------------------------------------
# GET /debate/{thread_id}/stream  –  SSE live event stream
# ---------------------------------------------------------------------------

@router.get(
    "/debate/{thread_id}/stream",
    tags=["debate"],
    summary="Subscribe to a live SSE stream of debate events.",
    response_class=StreamingResponse,
)
async def stream_debate_events(
    thread_id: str,
    request: Request,
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    active_runs: set[str] = Depends(get_active_runs),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
    db: aiosqlite.Connection = Depends(get_db),
):
    """SSE stream for live debate events.

    Supports ``Last-Event-ID`` header for reconnection replay: events saved
    after that ID are replayed before switching to live broadcast.
    If the debate is already finished (in memory or DB), emits the
    final_decision event immediately and closes.
    """
    # Parse Last-Event-ID for reconnect replay.
    # B1 Fix: browser EventSource re-connections send the cursor as a query param
    # (last_event_id) rather than the native Last-Event-ID header, so check both.
    last_event_id_raw = (
        request.headers.get("Last-Event-ID")
        or request.headers.get("last-event-id")
        or request.query_params.get("last_event_id")
    )
    last_event_id: int | None = None
    if last_event_id_raw:
        try:
            last_event_id = int(last_event_id_raw)
        except ValueError:
            pass

    def _sse_line(event_type: str, payload: dict) -> str:
        """Format a single SSE frame with id, event, and data lines."""
        event_id = payload.pop("_event_id", None)
        data = json.dumps(payload)
        id_line = f"id: {event_id}\n" if event_id is not None else ""
        return f"{id_line}event: {event_type}\ndata: {data}\n\n"

    # Already done – fast path (reconnect or fresh)
    if thread_id in decision_store:
        final_json = decision_store[thread_id].model_dump_json()

        async def _already_done_mem():
            yield f"event: final_decision\ndata: {final_json}\n\n"

        return StreamingResponse(
            _already_done_mem(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Check DB for completed debates not in memory (across server restarts)
    decision_from_db = await get_decision_json(db, thread_id)
    if decision_from_db:
        async def _already_done_db():
            yield f"event: final_decision\ndata: {decision_from_db}\n\n"

        return StreamingResponse(
            _already_done_db(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    recovered_state = debate_store.get(thread_id)
    if recovered_state is None:
        recovered_state = await _load_recovered_state(db, thread_id, active_runs)
        if recovered_state is not None:
            debate_store[thread_id] = recovered_state

    if thread_id not in debate_store:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="debate_not_found",
                detail=f"No debate session found with thread_id '{thread_id}'.",
            ).model_dump(),
        )

    # Register a personal queue BEFORE snapshotting the replay buffer
    # to guarantee no events fall through the gap.
    personal_queue: asyncio.Queue = asyncio.Queue()
    queue_list = all_queues.setdefault(thread_id, [])
    queue_list.append(personal_queue)  # synchronous – no await

    # Replay: prefer DB-persistent events (supports server restarts).
    # When Last-Event-ID is set, only replay events after that ID.
    replay_snapshot = await get_debate_events(db, thread_id, after_event_id=last_event_id)
    if not replay_snapshot and last_event_id is None:
        # Fall back to in-memory buffer for in-flight debates
        replay_snapshot = list(all_replays.get(thread_id, []))

    # Because the personal queue is registered before this snapshot is read,
    # an event persisted in that window can land in both replay_snapshot and
    # personal_queue. skip_up_to records the highest _event_id already
    # delivered via replay so the live loop below can drop that duplicate.
    skip_up_to = max(
        (p.get("_event_id", 0) for p in replay_snapshot),
        default=(last_event_id or 0),
    )

    async def event_generator():
        try:
            for payload in replay_snapshot:
                if await request.is_disconnected():
                    return
                event_type = payload.get("type", "message")
                yield _sse_line(event_type, dict(payload))

            # If the replay already delivered a terminal frame (cancelled/error/
            # final_decision), the client has what it needs — don't re-emit one
            # below and don't fall into the live-queue loop for nothing.
            # Only events after the latest resume describe the current run: a
            # resumed debate's history still contains the old error/cancel frame.
            last_resume = max(
                (i for i, p in enumerate(replay_snapshot) if p.get("type") == "debate_resumed"),
                default=-1,
            )
            replayed_terminal = any(
                p.get("type") in ("cancelled", "error", "final_decision")
                for p in replay_snapshot[last_resume + 1:]
            )
            if replayed_terminal:
                return
            _stored = debate_store.get(thread_id)  # NB1: safe .get() — store is empty after restart
            if thread_id not in background_tasks and _stored is not None:
                if _stored.status == "error":
                    recovery_payload = {
                        "type": "error",
                        "error": "debate_recovery_required",
                        "detail": _stored.termination_reason or "recovery_required_after_restart",
                    }
                    yield f"event: error\ndata: {json.dumps(recovery_payload)}\n\n"
                    return
                if _stored.status == "cancelled":
                    cancelled_payload = {
                        "type": "cancelled",
                        "thread_id": thread_id,
                        "detail": "Debate cancelled by user.",
                    }
                    yield f"event: cancelled\ndata: {json.dumps(cancelled_payload)}\n\n"
                    return
                if _stored.status in ("converged", "max_rounds_reached"):
                    # Finished, but no decision was found in memory or the DB
                    # (persisting it failed) — nothing will ever arrive live.
                    unavailable_payload = {
                        "type": "error",
                        "error": "decision_unavailable",
                        "detail": "The debate finished but its decision could not be loaded.",
                    }
                    yield f"event: error\ndata: {json.dumps(unavailable_payload)}\n\n"
                    return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(
                        personal_queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                    )
                    if payload is None:  # sentinel – debate finished
                        break
                    event_id = payload.get("_event_id")
                    if event_id is not None and event_id <= skip_up_to:
                        # Already delivered via the replay above.
                        continue
                    event_type = payload.get("type", "message")
                    yield _sse_line(event_type, dict(payload))
                except TimeoutError:
                    # A named event (not an SSE comment) so the browser's
                    # EventSource can see it and keep its stale-connection
                    # timer from firing during long quiet phases or HITL pauses.
                    yield "event: ping\ndata: {}\n\n"
        finally:
            try:
                queue_list.remove(personal_queue)
            except ValueError:
                pass
            # Drop the subscriber list we may have created for a debate that is
            # already over; a running or paused debate keeps it (its event writer
            # broadcasts to this exact list object).
            current = debate_store.get(thread_id)
            if (
                not queue_list
                and all_queues.get(thread_id) is queue_list
                and thread_id not in background_tasks
                and (current is None or current.status in _TERMINAL_STATUSES)
            ):
                all_queues.pop(thread_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# GET /debate/{thread_id}  –  status of an in-progress or completed debate
# ---------------------------------------------------------------------------

@router.get(
    "/debate/{thread_id}",
    response_model=DebateStatusResponse,
    tags=["debate"],
    summary="Get the current status and round history of a debate session.",
    responses={404: {"model": ErrorResponse}},
)
async def get_debate_status(
    thread_id: str,
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    active_runs: set[str] = Depends(get_active_runs),
    db: aiosqlite.Connection = Depends(get_db),
) -> DebateStatusResponse:
    """Return the live `DebateStatusResponse` for the given `thread_id`.  404 if unknown."""
    state = debate_store.get(thread_id)
    if state is None:
        state = await _load_recovered_state(db, thread_id, active_runs)
        if state is not None:
            debate_store[thread_id] = state
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="debate_not_found",
                detail=f"No debate session found with thread_id '{thread_id}'.",
            ).model_dump(),
        )
    if (
        state.status == "in_progress"
        and thread_id not in background_tasks
        and thread_id not in active_runs
    ):
        state.status = "error"
        state.termination_reason = state.termination_reason or "recovery_required_after_restart"
        state.touch()
        debate_store[thread_id] = state
        await upsert_debate(db, state)
    return DebateStatusResponse(
        thread_id=state.thread_id,
        status=state.status,
        current_round=state.current_round,
        total_rounds=state.max_rounds,
        agreement_score=state.agreement_score,
        rounds=state.rounds,
    )


# ---------------------------------------------------------------------------
# GET /decision/{thread_id}  –  final decision for a completed debate
# ---------------------------------------------------------------------------

@router.get(
    "/decision/{thread_id}",
    response_model=FinalDecision,
    tags=["debate"],
    summary="Get the final decision produced by a completed debate session.",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_decision(
    thread_id: str,
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    db: aiosqlite.Connection = Depends(get_db),
) -> FinalDecision:
    """Return the FinalDecision; falls back to the database across restarts."""
    if thread_id in decision_store:
        return decision_store[thread_id]

    decision_from_db = await get_decision_json(db, thread_id)
    if decision_from_db:
        decision = FinalDecision.model_validate_json(decision_from_db)
        decision_store[thread_id] = decision
        return decision

    if thread_id in debate_store:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_in_progress",
                detail=f"Debate '{thread_id}' has not yet produced a final decision.",
            ).model_dump(),
        )
    raise HTTPException(
        status_code=404,
        detail=ErrorResponse(
            error="debate_not_found",
            detail=f"No debate session found with thread_id '{thread_id}'.",
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# POST /debate/{thread_id}/resume  –  resume from LangGraph checkpoint
# ---------------------------------------------------------------------------

@router.post(
    "/debate/{thread_id}/resume",
    response_model=FinalDecision,
    tags=["debate"],
    summary="Resume an interrupted debate from its last LangGraph checkpoint.",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def resume_debate(
    thread_id: str,
    request: Request,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    active_runs: set[str] = Depends(get_active_runs),
    db: aiosqlite.Connection = Depends(get_db),
) -> FinalDecision | JSONResponse:
    """
    Resume a debate that was interrupted by a process restart or error.

    Loads execution state from the LangGraph ``AsyncSqliteSaver`` checkpoint
    and continues from the last completed graph node.

    - **400** – no LangGraph checkpoint found for this ``thread_id``
    - **404** – debate session does not exist
    - **409** – debate task is still running; cannot resume a live debate
    """
    # Fast-path: already completed in memory
    if thread_id in decision_store:
        return decision_store[thread_id]

    # Fast-path: completed and stored in DB across a restart
    completed_json = await get_decision_json(db, thread_id)
    if completed_json:
        return FinalDecision.model_validate_json(completed_json)

    # Locate the current debate state
    state = debate_store.get(thread_id)
    if state is None:
        state_json = await get_debate_state_json(db, thread_id)
        if not state_json:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error="debate_not_found",
                    detail=f"No debate session found with thread_id '{thread_id}'.",
                ).model_dump(),
            )
        state = DebateState.model_validate_json(state_json)
        debate_store[thread_id] = state

    # Reject if this debate is already executing: a background run/approval, or
    # another in-request resume. Checked before any await so it can't be raced.
    running = background_tasks.get(thread_id)
    if (running is not None and not running.done()) or thread_id in active_runs:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_in_progress",
                detail=f"Debate '{thread_id}' is still running. Cannot resume a live debate.",
            ).model_dump(),
        )

    # A debate paused for human review is continued through /approve; resuming it
    # here would only re-raise the pending interrupt and produce no decision.
    if state.status == "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_awaiting_approval",
                detail=(
                    f"Debate '{thread_id}' is paused for human review. "
                    f"Use POST /debate/{thread_id}/approve to continue it."
                ),
            ).model_dump(),
        )

    # Transition back to in_progress for the resume run. Track it as an active
    # run so a concurrent status poll doesn't mistake this genuine in_progress
    # state for an orphaned run and rewrite it to "error".
    with _track_active_run(active_runs, thread_id):
        state.status = "in_progress"
        state.touch()
        debate_store[thread_id] = state
        await _persist_debate_state(state, settings.DATABASE_URL)

        graph = DebateGraph(
            llm_client=llm_client,
            settings=settings,
            on_state_change=_track_state_changes(debate_store, settings.DATABASE_URL),
        )

        try:
            final_state, decision = await graph.resume(thread_id, prior_usage=state.token_usage_by_model)
        except ValueError as exc:
            # No checkpoint exists in the SQLite checkpoint DB
            state.status = "error"
            state.termination_reason = "no_checkpoint_for_resume"
            state.touch()
            debate_store[thread_id] = state
            await _persist_debate_state(state, settings.DATABASE_URL)
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error="no_checkpoint_available",
                    detail=str(exc),
                ).model_dump(),
            ) from exc
        except Exception as exc:
            error_type = type(exc).__name__
            logger.error(
                "api_debate_resume_failed",
                extra={"thread_id": thread_id, "error_type": error_type, "error": str(exc)},
            )
            # The resumed graph worked on a checkpoint copy; keep its newer rounds.
            current = debate_store.get(thread_id) or state
            current.status = "error"
            current.termination_reason = f"resume_failed:{error_type}"
            current.touch()
            debate_store[thread_id] = current
            await _persist_debate_state(current, settings.DATABASE_URL)
            raise HTTPException(
                status_code=500,
                detail=ErrorResponse(
                    error="resume_failed",
                    detail=f"Resume failed ({error_type}). {public_error_message(exc)}",
                ).model_dump(),
            ) from exc

        debate_store[thread_id] = final_state
        if decision is None:
            # The resumed run reached the HITL node and paused again: there is no
            # decision yet, so report the paused status instead of a decision.
            await _persist_debate_state(final_state, settings.DATABASE_URL)
            audit_event(
                "debate.resume",
                outcome="paused_for_approval",
                request=request,
                thread_id=thread_id,
            )
            return JSONResponse(
                status_code=202,
                content={
                    "thread_id": thread_id,
                    "status": final_state.status,
                    "current_round": final_state.current_round,
                    "total_rounds": final_state.max_rounds,
                },
            )
        decision_store[thread_id] = decision
        app_metrics.increment_event("debate.resumed")
        await _finish_debate(graph, final_state, decision, settings.DATABASE_URL)
        logger.info(
            "api_debate_resume_complete",
            extra={"thread_id": thread_id, "termination_reason": final_state.termination_reason},
        )
        audit_event(
            "debate.resume",
            outcome="success",
            request=request,
            thread_id=thread_id,
            termination_reason=final_state.termination_reason,
        )
        return decision


# ---------------------------------------------------------------------------
# POST /debate/{thread_id}/resume-async  –  resume in the background over SSE
# ---------------------------------------------------------------------------

@router.post(
    "/debate/{thread_id}/resume-async",
    tags=["debate"],
    status_code=202,
    summary="Resume an interrupted debate in the background; progress streams over SSE.",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def resume_debate_async(
    thread_id: str,
    request: Request,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    active_runs: set[str] = Depends(get_active_runs),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Continue an interrupted or failed debate from its last checkpoint without
    holding the request open; the stream URL delivers the continuation.

    - **400** – no checkpoint exists for this debate
    - **404** – no such debate
    - **409** – already finished, already running, or paused for review (use /approve)
    """
    from app.api.dependencies import get_knowledge_base, get_memory_store

    if thread_id in decision_store or await get_decision_json(db, thread_id):
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_already_completed",
                detail=f"Debate '{thread_id}' already has a final decision.",
            ).model_dump(),
        )
    state = debate_store.get(thread_id)
    if state is None:
        state = await _load_recovered_state(db, thread_id, active_runs)
        if state is not None:
            debate_store[thread_id] = state
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="debate_not_found",
                detail=f"No debate session found with thread_id '{thread_id}'.",
            ).model_dump(),
        )

    graph = DebateGraph(llm_client=llm_client, settings=settings)
    if not await graph.has_checkpoint(thread_id):
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="no_checkpoint_available",
                detail=f"Debate '{thread_id}' has no saved progress to resume from.",
            ).model_dump(),
        )

    # From here to task registration there is no await, so concurrent
    # resume/approve requests cannot both get through.
    running = background_tasks.get(thread_id)
    if (running is not None and not running.done()) or thread_id in active_runs:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_in_progress",
                detail=f"Debate '{thread_id}' is already running.",
            ).model_dump(),
        )
    if state.status == "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_awaiting_approval",
                detail=(
                    f"Debate '{thread_id}' is paused for human review. "
                    f"Use POST /debate/{thread_id}/approve to continue it."
                ),
            ).model_dump(),
        )

    state.status = "in_progress"
    state.touch()
    queue_list = all_queues.setdefault(thread_id, [])
    replay_buffer = all_replays.setdefault(thread_id, [])
    persist_queue: asyncio.Queue = asyncio.Queue()
    writer_task = asyncio.create_task(
        _event_writer_loop(persist_queue, queue_list, replay_buffer, thread_id, settings.DATABASE_URL)
    )
    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        queue_list=queue_list,
        replay_buffer=replay_buffer,
        persist_queue=persist_queue,
        on_state_change=_track_state_changes(debate_store, settings.DATABASE_URL),
        knowledge_base=get_knowledge_base(),
        memory_store=get_memory_store(),
    )
    task = asyncio.create_task(
        _run_debate_background(
            graph, state, debate_store, decision_store,
            all_queues, all_replays, settings.DATABASE_URL,
            persist_queue=persist_queue,
            writer_task=writer_task,
            runner=lambda: graph.resume(thread_id, prior_usage=state.token_usage_by_model),
            completed_metric="debate.resumed",
        )
    )
    background_tasks[thread_id] = task
    task.add_done_callback(_forget_task(background_tasks, thread_id))
    audit_event("debate.resume_async", outcome="accepted", request=request, thread_id=thread_id)
    return {"thread_id": thread_id, "status": "resuming"}


# ---------------------------------------------------------------------------
# POST /debate/{thread_id}/cancel  –  cancel an in-flight async debate
# ---------------------------------------------------------------------------

@router.post(
    "/debate/{thread_id}/cancel",
    tags=["debate"],
    summary="Cancel an in-flight async debate so it stops making further LLM calls.",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def cancel_debate(
    thread_id: str,
    request: Request,
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    active_runs: set[str] = Depends(get_active_runs),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """
    Request cancellation of a running background debate.

    Calls ``task.cancel()``; the background runner catches ``CancelledError``,
    sets status ``cancelled``, persists, and emits a terminal ``cancelled`` SSE
    event.  Cancellation takes effect at the next graph await boundary.

    - **404** – no such debate session
    A debate paused for human review has no running task; it is cancelled
    directly (status ``cancelled`` plus a terminal ``cancelled`` SSE event).

    - **404** – no such debate session
    - **409** – the debate exists but is not actively running (already finished/cancelled)
    """
    task = background_tasks.get(thread_id)
    if task is None or task.done():
        state = debate_store.get(thread_id)
        if state is None:
            state = await _load_recovered_state(db, thread_id, active_runs)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error="debate_not_found",
                    detail=f"No debate session found with thread_id '{thread_id}'.",
                ).model_dump(),
            )
        if state.status == "awaiting_approval" and thread_id not in active_runs:
            await _cancel_paused_debate(state, debate_store, all_queues, all_replays, db)
            app_metrics.increment_event("debate.cancelled")
            audit_event("debate.cancel", outcome="success", request=request, thread_id=thread_id)
            return {"thread_id": thread_id, "status": "cancelled"}
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_not_running",
                detail=f"Debate '{thread_id}' is not actively running and cannot be cancelled.",
            ).model_dump(),
        )

    task.cancel()
    logger.info("api_debate_cancel_requested", extra={"thread_id": thread_id})
    audit_event(
        "debate.cancel",
        outcome="requested",
        request=request,
        thread_id=thread_id,
    )
    return {"thread_id": thread_id, "status": "cancelling"}


# ---------------------------------------------------------------------------
# GET /history  –  paginated list of completed debates
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=HistoryListResponse,
    tags=["history"],
    summary="List completed debates with optional full-text search.",
)
async def list_history(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, description="Search query & decision text."),
    sort: Literal["newest", "oldest", "highest_agreement"] = Query(default="newest"),
    termination_reason: Literal["consensus_reached", "human_override", "max_rounds_reached"] | None = Query(
        default=None, description="Only debates that ended this way."
    ),
    db: aiosqlite.Connection = Depends(get_db),
) -> HistoryListResponse:
    items_raw, total = await get_history(
        db, page=page, limit=limit, q=q, sort=sort, termination_reason=termination_reason
    )
    return HistoryListResponse(
        items=[HistoryItem(**item) for item in items_raw],
        total=total,
        page=page,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /metrics  –  lightweight application metrics snapshot
# ---------------------------------------------------------------------------

@router.get(
    "/metrics",
    tags=["system"],
    summary="Return lightweight application metrics for dashboards and diagnostics.",
)
async def get_metrics() -> dict:
    """Expose in-process counters for requests and key debate lifecycle events."""
    return app_metrics.snapshot()


# ---------------------------------------------------------------------------
# GET /history/{thread_id}  –  single persisted decision
# ---------------------------------------------------------------------------

@router.get(
    "/history/{thread_id}",
    response_model=FinalDecision,
    tags=["history"],
    summary="Retrieve a persisted debate decision by thread ID.",
    responses={404: {"model": ErrorResponse}},
)
async def get_history_item(
    thread_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
) -> FinalDecision:
    if thread_id in decision_store:
        return decision_store[thread_id]

    decision_from_db = await get_decision_json(db, thread_id)
    if not decision_from_db:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="decision_not_found",
                detail=f"No persisted decision found for thread_id '{thread_id}'.",
            ).model_dump(),
        )
    return FinalDecision.model_validate_json(decision_from_db)


# ---------------------------------------------------------------------------
# GET /agents  –  list all registered agents and their configs
# ---------------------------------------------------------------------------

@router.get(
    "/agents",
    tags=["agents"],
    summary="List all registered debate agents and their configurations.",
)
async def list_agents() -> list[dict]:
    """Return a list of all agents registered in the AgentRegistry."""
    return [
        {
            "name": cfg.name,
            "role": cfg.role,
            "icon": cfg.icon,
            "enabled": cfg.enabled,
            "model_provider": cfg.model_provider,
            "model_name": cfg.model_name,
            "temperature": cfg.temperature,
        }
        for cfg in registry.list_agents()
    ]


# ---------------------------------------------------------------------------
# GET /templates  –  list built-in debate templates
# ---------------------------------------------------------------------------

@router.get(
    "/templates",
    tags=["templates"],
    summary="List all built-in debate templates.",
)
async def list_templates(
    category: str | None = Query(default=None, description="Filter by category name."),
    q: str | None = Query(default=None, description="Full-text search on title, query, and tags."),
) -> list[dict]:
    """Return all built-in debate templates, optionally filtered."""
    results = TEMPLATES
    if category:
        results = [t for t in results if t.category.lower() == category.lower()]
    if q:
        q_lower = q.lower()
        results = [
            t for t in results
            if q_lower in t.title.lower()
            or q_lower in t.query.lower()
            or any(q_lower in tag for tag in t.tags)
        ]
    return [t.model_dump() for t in results]


# ---------------------------------------------------------------------------
# GET /decision/{thread_id}/export  –  export decision as Markdown or PDF
# ---------------------------------------------------------------------------

@router.get(
    "/decision/{thread_id}/export",
    tags=["decisions"],
    summary="Export a completed debate decision as Markdown or PDF.",
)
async def export_decision(
    thread_id: str,
    format: str = Query(default="markdown", description="Export format: 'markdown' or 'pdf'."),
    db: aiosqlite.Connection = Depends(get_db),
) -> StreamingResponse:
    """Download a FinalDecision document in Markdown or PDF format."""
    from app.services.exporter import render_markdown, render_pdf

    decision_json = await get_decision_json(db, thread_id)
    if decision_json is None:
        raise HTTPException(status_code=404, detail="Decision not found.")

    decision = FinalDecision.model_validate_json(decision_json)

    fmt = format.lower()

    # NB6: validate before processing — unknown formats return 400, not silent markdown
    if fmt not in ("markdown", "pdf", "json"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{fmt}'. Supported: 'markdown', 'pdf', 'json'.",
        )

    if fmt == "pdf":
        try:
            # WeasyPrint is CPU-bound; render off the event loop so live streams don't stall.
            pdf_bytes = await asyncio.to_thread(render_pdf, decision)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="decision-{thread_id}.pdf"'
            },
        )

    # FI4: JSON export — machine-readable full decision object
    if fmt == "json":
        return StreamingResponse(
            iter([decision.model_dump_json(indent=2).encode("utf-8")]),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="decision-{thread_id}.json"'
            },
        )

    # Default: markdown
    md = render_markdown(decision)
    return StreamingResponse(
        iter([md.encode("utf-8")]),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="decision-{thread_id}.md"'
        },
    )


# ---------------------------------------------------------------------------
# P4.1  POST /debate/{thread_id}/approve  –  HITL approval
# ---------------------------------------------------------------------------

@router.post(
    "/debate/{thread_id}/approve",
    tags=["debate"],
    summary="Approve, override, or extend a debate that is awaiting human review.",
    status_code=202,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def approve_debate(
    thread_id: str,
    request: Request,
    body: ApproveRequest,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    background_tasks: dict[str, asyncio.Task] = Depends(get_background_tasks),
    active_runs: set[str] = Depends(get_active_runs),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Continue a HITL-paused debate with the reviewer's action, in the background.

    Returns 202 straight away; the continuation (another round, or the final
    decision) streams over SSE exactly like a freshly started debate, so the
    request never outlives proxy timeouts and the UI never races its own stream.

    - **404** – no such debate
    - **409** – the debate is already running, or is not awaiting approval
    """
    from app.api.dependencies import get_knowledge_base, get_memory_store

    state = debate_store.get(thread_id)
    if state is None:
        state = await _load_recovered_state(db, thread_id, active_runs)
        if state is not None:
            debate_store[thread_id] = state
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="debate_not_found",
                detail=f"No debate session found with thread_id '{thread_id}'.",
            ).model_dump(),
        )

    # Nothing below awaits until the task is registered, so a second approval
    # (double click, second tab, retry after a timeout) is rejected here.
    running = background_tasks.get(thread_id)
    if (running is not None and not running.done()) or thread_id in active_runs:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_in_progress",
                detail=f"Debate '{thread_id}' is already running.",
            ).model_dump(),
        )
    if body.action == "add_round" and state.max_rounds >= MAX_DEBATE_ROUNDS_LIMIT:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="round_limit_reached",
                detail=f"A debate can run at most {MAX_DEBATE_ROUNDS_LIMIT} rounds.",
            ).model_dump(),
        )
    if state.status != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_not_awaiting_approval",
                detail=f"Debate '{thread_id}' is not awaiting approval (status: {state.status}).",
            ).model_dump(),
        )

    state.status = "in_progress"
    state.touch()

    queue_list = all_queues.setdefault(thread_id, [])
    replay_buffer = all_replays.setdefault(thread_id, [])
    persist_queue: asyncio.Queue = asyncio.Queue()
    writer_task = asyncio.create_task(
        _event_writer_loop(persist_queue, queue_list, replay_buffer, thread_id, settings.DATABASE_URL)
    )
    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        queue_list=queue_list,
        replay_buffer=replay_buffer,
        persist_queue=persist_queue,
        on_state_change=_track_state_changes(debate_store, settings.DATABASE_URL),
        knowledge_base=get_knowledge_base(),
        memory_store=get_memory_store(),
    )
    task = asyncio.create_task(
        _run_debate_background(
            graph, state, debate_store, decision_store,
            all_queues, all_replays, settings.DATABASE_URL,
            persist_queue=persist_queue,
            writer_task=writer_task,
            runner=lambda: graph.approve(
                thread_id,
                action=body.action,
                feedback=body.feedback,
                prior_usage=state.token_usage_by_model,
            ),
            completed_metric="debate.approved",
        )
    )
    background_tasks[thread_id] = task
    task.add_done_callback(_forget_task(background_tasks, thread_id))

    audit_event(
        "debate.approve",
        outcome="accepted",
        request=request,
        thread_id=thread_id,
        action_requested=body.action,
    )
    return {"thread_id": thread_id, "status": "resuming", "action": body.action}


# ---------------------------------------------------------------------------
# P4.2  POST /debate/simulate  –  scenario simulation
# ---------------------------------------------------------------------------

@router.post(
    "/debate/simulate",
    tags=["debate"],
    summary="Run N independent parallel debates and return stability metrics.",
)
@limiter.limit(f"{app_settings.RATE_LIMIT_PER_MINUTE}/minute")
@limiter.limit("2/hour")  # B9: simulation fans out to 2–5 full debates; tighter hourly cap
async def simulate_debate(
    request: Request,
    body: SimulateRequest,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
):
    """Run N independent parallel debates for the query and return a SimulationResult.

    Holds the request open for every run; browsers should use
    ``/debate/simulate-async`` (a polled job) so proxy timeouts don't cut it off.
    """
    result = await _simulate(body, llm_client, settings)
    audit_event(
        "debate.simulate",
        outcome="success",
        request=request,
        runs=body.runs,
        mode=body.mode,
    )
    return result.model_dump()


def _resolve_simulation_agents(body: SimulateRequest) -> list[str] | None:
    """Participants exactly as a single debate would resolve them: a domain pack
    overrides the explicit agents list."""
    if body.domain_pack:
        from app.data.domain_packs import DOMAIN_PACKS_BY_ID

        pack = DOMAIN_PACKS_BY_ID.get(body.domain_pack)
        if pack is None:
            raise HTTPException(
                status_code=422,
                detail=ErrorResponse(
                    error="unknown_domain_pack",
                    detail=f"Unknown domain pack '{body.domain_pack}'.",
                ).model_dump(),
            )
        return list(pack.agents)
    if body.agents:
        unknown = [a for a in body.agents if not registry.is_registered(a)]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=ErrorResponse(
                    error="unknown_agents",
                    detail=f"Requested agents are not registered: {unknown}",
                ).model_dump(),
            )
        return list(body.agents)
    return None


async def _simulate(
    body: SimulateRequest,
    llm_client: LangChainProvider,
    settings: Settings,
    selected_agents: list[str] | None = None,
    resolved: bool = False,
):
    """Run the simulation described by ``body`` and return its SimulationResult."""
    from app.api.dependencies import get_knowledge_base, get_memory_store
    from app.services.simulation import run_simulation

    if not resolved:
        selected_agents = _resolve_simulation_agents(body)
    result = await run_simulation(
        query=body.query,
        runs=body.runs,
        max_rounds=body.max_rounds,
        mode=body.mode,
        llm_client=llm_client,
        settings=settings,
        selected_agents=selected_agents,
        knowledge_base=get_knowledge_base() if body.use_knowledge_base else None,
        memory_store=get_memory_store() if body.enable_agent_memory else None,
        use_knowledge_base=body.use_knowledge_base,
        enable_agent_memory=body.enable_agent_memory,
        agreement_method=body.agreement_method,
    )
    app_metrics.increment_event("debate.simulated")
    return result


# Finished simulation jobs are kept this long (seconds) for the client to fetch.
_SIMULATION_JOB_TTL_SECONDS = 3600.0


def _prune_simulation_jobs(jobs: dict[str, dict]) -> None:
    now = time.monotonic()
    for job_id in [
        jid for jid, job in jobs.items()
        if job["status"] != "running" and now - job["finished_at"] > _SIMULATION_JOB_TTL_SECONDS
    ]:
        jobs.pop(job_id, None)


async def _run_simulation_job(job: dict, body: SimulateRequest, llm_client, settings, selected_agents) -> None:
    try:
        result = await _simulate(body, llm_client, settings, selected_agents, resolved=True)
        job.update(status="completed", result=result.model_dump())
    except asyncio.CancelledError:
        job.update(status="cancelled")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "simulation_job_failed",
            extra={"job_id": job["job_id"], "error_type": type(exc).__name__, "error": str(exc)},
        )
        job.update(status="failed", error=public_error_message(exc))
    finally:
        job["finished_at"] = time.monotonic()


def _job_view(job: dict) -> dict:
    return {key: job[key] for key in ("job_id", "status", "result", "error")}


@router.post(
    "/debate/simulate-async",
    tags=["debate"],
    status_code=202,
    summary="Start a scenario simulation as a background job; poll its status URL.",
)
@limiter.limit(f"{app_settings.RATE_LIMIT_PER_MINUTE}/minute")
@limiter.limit("2/hour")  # same cap as /debate/simulate: each job fans out to 2–5 debates
async def start_simulation_job(
    request: Request,
    body: SimulateRequest,
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    jobs: dict[str, dict] = Depends(get_simulation_jobs),
) -> dict:
    selected_agents = _resolve_simulation_agents(body)
    _prune_simulation_jobs(jobs)
    job_id = str(uuid.uuid4())
    job: dict = {"job_id": job_id, "status": "running", "result": None, "error": None, "finished_at": 0.0}
    job["task"] = asyncio.create_task(_run_simulation_job(job, body, llm_client, settings, selected_agents))
    jobs[job_id] = job
    audit_event("debate.simulate_async", outcome="accepted", request=request, runs=body.runs, mode=body.mode)
    return {**_job_view(job), "status_url": f"/debate/simulate/{job_id}"}


def _get_job_or_404(jobs: dict[str, dict], job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(error="simulation_not_found", detail=f"No simulation job '{job_id}'.").model_dump(),
        )
    return job


@router.get("/debate/simulate/{job_id}", tags=["debate"], summary="Status (and result, once done) of a simulation job.")
async def get_simulation_job(job_id: str, jobs: dict[str, dict] = Depends(get_simulation_jobs)) -> dict:
    return _job_view(_get_job_or_404(jobs, job_id))


@router.post("/debate/simulate/{job_id}/cancel", tags=["debate"], summary="Cancel a running simulation job.")
async def cancel_simulation_job(job_id: str, jobs: dict[str, dict] = Depends(get_simulation_jobs)) -> dict:
    job = _get_job_or_404(jobs, job_id)
    task: asyncio.Task = job["task"]
    if job["status"] == "running" and not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=10)
    return _job_view(job)


# ---------------------------------------------------------------------------
# P4.3  POST /decision/{thread_id}/evaluate  –  decision quality evaluation
# ---------------------------------------------------------------------------

@router.post(
    "/decision/{thread_id}/evaluate",
    tags=["decisions"],
    summary="Evaluate the quality of a completed decision (LLM-as-judge). Cached after first call.",
    responses={404: {"model": ErrorResponse}},
)
async def evaluate_decision_endpoint(
    thread_id: str,
    request: Request,
    llm_client: LangChainProvider = Depends(get_groq_client),
    db: aiosqlite.Connection = Depends(get_db),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
):
    """Return an EvaluationResult for the decision.  Cached in DB after the first evaluation."""
    from app.services.evaluator import evaluate_decision

    # Return cached result if available
    cached_json = await get_evaluation_json(db, thread_id)
    if cached_json:
        import json as _json
        return _json.loads(cached_json)

    # Get the decision
    decision: FinalDecision | None = decision_store.get(thread_id)
    if decision is None:
        decision_json = await get_decision_json(db, thread_id)
        if not decision_json:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error="decision_not_found",
                    detail=f"No decision found for thread_id '{thread_id}'.",
                ).model_dump(),
            )
        decision = FinalDecision.model_validate_json(decision_json)

    result = await evaluate_decision(decision, llm_client=llm_client)
    result_json = result.model_dump_json()
    await save_evaluation(db, thread_id, result_json)
    invalidate_analytics_cache()
    app_metrics.increment_event("decision.evaluated")
    audit_event(
        "decision.evaluate",
        outcome="success",
        request=request,
        thread_id=thread_id,
    )
    return result.model_dump()


# ---------------------------------------------------------------------------
# P3.1  Knowledge base endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/knowledge/upload",
    tags=["knowledge"],
    summary="Upload a document to the knowledge base (PDF, TXT, or Markdown).",
)
@limiter.limit("10/minute")
async def upload_knowledge_document(
    request: Request,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    """Ingest a document into the ChromaDB knowledge base."""
    import os
    import pathlib
    import tempfile

    from app.api.dependencies import get_knowledge_base

    kb = get_knowledge_base()
    if not kb.is_available:
        raise HTTPException(
            status_code=501,
            detail="Knowledge base is not available (chromadb not installed).",
        )

    # Validate file extension
    allowed_exts = {".pdf", ".txt", ".md"}
    suffix = pathlib.Path(file.filename or "file.txt").suffix.lower()
    if suffix not in allowed_exts:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(allowed_exts)}",
        )

    # Size limit from settings. Oversized requests with a Content-Length are
    # already refused by UploadSizeLimitMiddleware before the body is parsed.
    max_bytes = settings.KB_MAX_FILE_MB * 1024 * 1024
    too_large = HTTPException(
        status_code=413,
        detail=f"File too large (max {settings.KB_MAX_FILE_MB} MB).",
    )
    if file.size is not None and file.size > max_bytes:
        raise too_large

    # Copy to a temp file in chunks (never the whole upload in memory), then ingest.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        written = 0
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                break
            tmp.write(chunk)

    try:
        if written > max_bytes:
            raise too_large
        # R1: kb.ingest is a coroutine — await it directly (not via asyncio.to_thread)
        chunks = await kb.ingest(tmp_path, {"source": file.filename or "upload"})
    except KnowledgeBaseUnavailable as exc:
        raise HTTPException(status_code=501, detail="Knowledge base is not available.") from exc
    finally:
        os.unlink(tmp_path)

    # R9: warn when no text could be extracted (e.g. scanned/image-only PDF)
    if chunks == 0:
        raise HTTPException(
            status_code=422,
            detail="No extractable text found in this file. Is it a scanned or image-only PDF?",
        )

    app_metrics.increment_event("knowledge.uploaded")
    audit_event(
        "knowledge.upload",
        outcome="success",
        request=request,
        document=file.filename,
        chunks_indexed=chunks,
    )
    return {"filename": file.filename, "chunks_indexed": chunks}


@router.get(
    "/knowledge/documents",
    tags=["knowledge"],
    summary="List all documents currently indexed in the knowledge base.",
)
async def list_knowledge_documents():
    """Return a list of document names and their chunk counts."""
    from app.api.dependencies import get_knowledge_base

    kb = get_knowledge_base()
    if not kb.is_available:
        return []
    return await kb.list_documents()  # R1: was missing await


@router.delete(
    "/knowledge/documents/{doc_name:path}",
    tags=["knowledge"],
    summary="Remove a document from the knowledge base.",
)
async def delete_knowledge_document(
    doc_name: str,
    request: Request,
    _admin: None = Depends(require_admin),
):
    """Delete all chunks for the given document name."""
    from app.api.dependencies import get_knowledge_base

    kb = get_knowledge_base()
    if not kb.is_available:
        raise HTTPException(status_code=501, detail="Knowledge base not available.")
    deleted = await kb.delete_document(doc_name)  # R1: was missing await
    app_metrics.increment_event("knowledge.deleted")
    audit_event(
        "knowledge.delete",
        outcome="success",
        request=request,
        document=doc_name,
        chunks_deleted=deleted,
    )
    return {"doc_name": doc_name, "chunks_deleted": deleted}


# ---------------------------------------------------------------------------
# P3.3  Agent memory endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/memory/{agent_name}",
    tags=["memory"],
    summary="Get the stored memory lessons for an agent.",
)
async def get_agent_memory(
    agent_name: str,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return the most recent memory entries for the named agent."""
    from app.api.dependencies import get_memory_store

    ms = get_memory_store()
    if ms is None:
        return []
    entries = await ms.get_all_memory(agent_name, limit=limit)
    return entries


@router.delete(
    "/memory/{agent_name}",
    tags=["memory"],
    summary="Clear all stored memory for an agent.",
)
async def clear_agent_memory(
    agent_name: str,
    request: Request,
    _admin: None = Depends(require_admin),
):
    """Delete every memory entry for the named agent."""
    from app.api.dependencies import get_memory_store

    ms = get_memory_store()
    if ms is None:
        return {"agent_name": agent_name, "deleted": 0}
    deleted = await ms.clear_memory(agent_name)
    app_metrics.increment_event("memory.cleared")
    audit_event(
        "memory.clear",
        outcome="success",
        request=request,
        agent_name=agent_name,
        deleted=deleted,
    )
    return {"agent_name": agent_name, "deleted": deleted}


# ---------------------------------------------------------------------------
# P3.4  Domain packs endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/domain-packs",
    tags=["agents"],
    summary="List all available domain agent packs.",
)
async def list_domain_packs():
    """Return the built-in domain packs (Finance, Engineering, Legal, Healthcare)."""
    from app.data.domain_packs import DOMAIN_PACKS_BY_ID

    return list(DOMAIN_PACKS_BY_ID.values())


@router.get(
    "/debate-modes",
    response_model=DebateModesResponse,
    tags=["debate"],
    summary="Debate mode presets and the configured default mode.",
)
async def list_debate_modes() -> DebateModesResponse:
    """The default comes from DEFAULT_DEBATE_MODE (Quick when not set); the UI pre-selects it."""
    return DebateModesResponse(
        default_mode=default_debate_mode(),
        presets=mode_presets(),
        default_agreement_method=app_settings.AGREEMENT_METHOD,
        semantic_available=semantic_available(),
    )


# ---------------------------------------------------------------------------
# LLM provider settings — runtime switching from the UI
# ---------------------------------------------------------------------------

@router.get(
    "/llm-settings",
    response_model=LLMSettingsResponse,
    tags=["system"],
    summary="Get the currently active LLM provider and model.",
)
async def get_llm_settings() -> LLMSettingsResponse:
    """
    Returns the active provider, model, available choices, and whether
    a user-supplied API key is in use.  Never exposes API key values.
    """
    info = get_active_provider_info()
    return LLMSettingsResponse(
        provider=info["provider"],
        model=info["model"],
        available_models=PROVIDER_MODELS,
        using_custom_key=info["using_custom_key"],
        server_keys={p: bool(server_api_key(p)) for p in PROVIDER_MODELS},
        admin_token_required=admin_token_required(),
    )


@router.post(
    "/llm-settings",
    response_model=LLMSettingsResponse,
    tags=["system"],
    summary="Switch the active LLM provider and model at runtime.",
)
async def update_llm_settings(
    body: LLMSettingsUpdate,
    _admin: None = Depends(require_admin),
) -> LLMSettingsResponse:
    """
    Switches the global LLM singleton to the requested provider/model.

    This changes the provider for **every** user of the deployment, so it is an
    administrative action (see ``ADMIN_API_TOKEN``). The server's configured key
    for the provider is used unless the caller supplies ``api_key``, which is
    held in memory only — never persisted to disk.
    """
    api_key = body.api_key or server_api_key(body.provider)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="api_key_required",
                detail=f"No API key is configured on the server for '{body.provider}'; supply one.",
            ).model_dump(),
        )

    reset_llm_client(
        provider=body.provider, api_key=api_key, model=body.model, custom_key=bool(body.api_key)
    )
    logger.info(
        "llm_provider_switched_via_api",
        extra={"provider": body.provider, "model": body.model},
    )
    return LLMSettingsResponse(
        provider=body.provider,
        model=body.model,
        available_models=PROVIDER_MODELS,
        using_custom_key=bool(body.api_key),
        server_keys={p: bool(server_api_key(p)) for p in PROVIDER_MODELS},
        admin_token_required=admin_token_required(),
    )

