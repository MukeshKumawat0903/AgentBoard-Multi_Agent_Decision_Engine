"""
API route definitions for AgentBoard.

All REST endpoints are defined here and included
via the main FastAPI application router.
"""

import asyncio
import json
import logging

import aiosqlite
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_background_tasks,
    get_db,
    get_debate_store,
    get_decision_store,
    get_event_queues,
    get_event_replays,
    get_groq_client,
    get_settings,
)
from app.core.config import Settings
from app.core.config import settings as app_settings
from app.db.crud import get_decision_json, get_history, save_decision, upsert_debate
from app.db.crud import get_debate_events, get_debate_state_json, save_debate_event
from app.db.crud import get_evaluation_json, save_evaluation
from app.orchestrator.debate_graph import DebateGraph
from app.schemas.state import DebateState
from app.schemas.api_models import (
    AsyncDebateStartResponse,
    DebateMode,
    DebateStartRequest,
    DebateStatusResponse,
    ErrorResponse,
    HistoryItem,
    HistoryListResponse,
    LLMSettingsResponse,
    LLMSettingsUpdate,
    PROVIDER_MODELS,
    resolve_debate_config,
)
from app.schemas.final_decision import FinalDecision
from app.core.audit import audit_event
from app.core.metrics import app_metrics
from app.core.rate_limiter import limiter
from app.services.llm_client import LangChainProvider, get_active_provider_info, reset_llm_client
from app.agents.registry import registry
from app.data.templates import TEMPLATES, TEMPLATES_BY_ID
from app.api.dependencies import get_thread_lock

router = APIRouter()
logger = logging.getLogger("agentboard.api")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _persist_debate(state: DebateState, decision: FinalDecision, database_url: str) -> None:
    """Persist a completed debate to the SQLite database (fire-and-forget)."""
    try:
        async with aiosqlite.connect(database_url) as db:
            await upsert_debate(db, state)
            await save_decision(db, decision, state.user_query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_persist_failed", extra={"error": str(exc)})


async def _persist_debate_state(state: DebateState, database_url: str) -> None:
    """Persist the latest DebateState snapshot for recovery and status lookups."""
    try:
        async with aiosqlite.connect(database_url) as db:
            await upsert_debate(db, state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_state_persist_failed", extra={"error": str(exc)})


async def _persist_event(thread_id: str, payload: dict, database_url: str) -> None:
    """Persist a replayable event payload for SSE recovery across restarts."""
    try:
        async with aiosqlite.connect(database_url) as db:
            await save_debate_event(db, thread_id, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_event_persist_failed", extra={"error": str(exc)})


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
) -> DebateState | None:
    """Load a DebateState snapshot and convert orphaned in-progress runs to error."""
    state_json = await get_debate_state_json(db, thread_id)
    if not state_json:
        return None
    state = DebateState.model_validate_json(state_json)
    if state.status == "in_progress":
        state.status = "error"
        state.termination_reason = state.termination_reason or "recovery_required_after_restart"
        state.touch()
        await upsert_debate(db, state)
    return state


async def _run_debate_background(
    graph: DebateGraph,
    debate_state: DebateState,
    debate_store: dict,
    decision_store: dict,
    all_queues: dict,
    database_url: str,
    consensus_threshold: float | None = None,
    skip_critique_phase: bool = False,
    hitl_mode: bool = False,
) -> None:
    """Run the debate graph, persist results, then close all subscriber queues."""
    thread_id = debate_state.thread_id
    should_close_streams = True
    lock = get_thread_lock(thread_id)
    try:
        final_state, decision = await graph.run(
            debate_state.user_query,
            initial_state=debate_state,
            consensus_threshold=consensus_threshold,
            skip_critique_phase=skip_critique_phase,
            hitl_mode=hitl_mode,
        )
        async with lock:
            debate_store[thread_id] = final_state
        if decision is None and final_state.status == "awaiting_approval":
            should_close_streams = False
            app_metrics.increment_event("debate.awaiting_approval")
            await _persist_debate_state(final_state, database_url)
            logger.info("background_debate_paused_for_approval", extra={"thread_id": thread_id})
            return

        async with lock:
            decision_store[thread_id] = decision
        app_metrics.increment_event("debate.completed_async")
        await _persist_debate(final_state, decision, database_url)
        final_payload = json.loads(decision.model_dump_json())
        final_payload["type"] = "final_decision"
        queue_list = all_queues.get(thread_id, [])
        for q in list(queue_list):
            q.put_nowait(final_payload)
    except Exception as exc:  # noqa: BLE001
        error_type = type(exc).__name__
        logger.error(
            "background_debate_failed",
            extra={"thread_id": thread_id, "error_type": error_type, "error": str(exc)},
        )
        app_metrics.increment_event("debate.failed_async")
        debate_state.status = "error"
        debate_state.termination_reason = f"error:{error_type}"
        debate_store[thread_id] = debate_state
        # Best-effort: persist the failed state so the UI can show an error banner
        try:
            async with aiosqlite.connect(database_url) as db:
                await upsert_debate(db, debate_state)
        except Exception:  # noqa: BLE001
            pass
        # Notify SSE subscribers that the debate failed
        error_payload = {
            "type": "error",
            "error": "debate_execution_failed",
            "error_type": error_type,
            "detail": str(exc),
        }
        for q in list(all_queues.get(thread_id, [])):
            q.put_nowait(error_payload)
    finally:
        if should_close_streams:
            for q in list(all_queues.get(thread_id, [])):
                q.put_nowait(None)


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
    resolved_rounds, resolved_threshold, resolved_skip = resolve_debate_config(
        mode=body.mode,
        max_rounds=body.max_rounds,
        consensus_threshold=body.consensus_threshold,
        skip_critique_phase=body.skip_critique_phase,
        default_max_rounds=settings.MAX_DEBATE_ROUNDS,
        default_threshold=settings.CONSENSUS_THRESHOLD,
    )
    from app.api.dependencies import get_knowledge_base, get_memory_store
    kb = get_knowledge_base() if body.use_knowledge_base else None
    ms = get_memory_store() if body.enable_agent_memory else None

    debate_state = DebateState(
        user_query=body.query,
        max_rounds=resolved_rounds,
        use_knowledge_base=bool(body.use_knowledge_base),
        enable_agent_memory=bool(body.enable_agent_memory),
        selected_agents=selected_agents,
        domain_pack=domain_pack,
    )
    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        on_state_change=lambda state: _persist_debate_state(state, settings.DATABASE_URL),
        knowledge_base=kb,
        memory_store=ms,
        selected_agents=selected_agents,
    )
    logger.info("api_debate_start")
    state, decision = await graph.run(
        body.query,
        initial_state=debate_state,
        consensus_threshold=resolved_threshold,
        skip_critique_phase=resolved_skip,
    )
    debate_store[state.thread_id] = state
    decision_store[state.thread_id] = decision
    app_metrics.increment_event("debate.started_sync")
    app_metrics.increment_event("debate.completed_sync")
    await _persist_debate(state, decision, settings.DATABASE_URL)
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
    resolved_rounds, resolved_threshold, resolved_skip = resolve_debate_config(
        mode=body.mode,
        max_rounds=body.max_rounds,
        consensus_threshold=body.consensus_threshold,
        skip_critique_phase=body.skip_critique_phase,
        default_max_rounds=settings.MAX_DEBATE_ROUNDS,
        default_threshold=settings.CONSENSUS_THRESHOLD,
    )
    debate_state = DebateState(
        user_query=body.query,
        max_rounds=resolved_rounds,
        use_knowledge_base=bool(body.use_knowledge_base),
        enable_agent_memory=bool(body.enable_agent_memory),
        selected_agents=selected_agents,
        domain_pack=domain_pack,
    )
    thread_id = debate_state.thread_id
    queue_list: list = []
    replay_buffer: list = []
    all_queues[thread_id] = queue_list
    all_replays[thread_id] = replay_buffer
    debate_store[thread_id] = debate_state
    await _persist_debate_state(debate_state, settings.DATABASE_URL)

    from app.api.dependencies import get_knowledge_base, get_memory_store
    kb = get_knowledge_base() if body.use_knowledge_base else None
    ms = get_memory_store() if body.enable_agent_memory else None

    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        queue_list=queue_list,
        replay_buffer=replay_buffer,
        on_state_change=lambda state: _persist_debate_state(state, settings.DATABASE_URL),
        on_event=lambda payload, tid=thread_id: _persist_event(tid, payload, settings.DATABASE_URL),
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
            all_queues, settings.DATABASE_URL,
            consensus_threshold=resolved_threshold,
            skip_critique_phase=resolved_skip,
            hitl_mode=bool(body.supervised),
        )
    )
    background_tasks[thread_id] = task
    task.add_done_callback(lambda _task, tid=thread_id: background_tasks.pop(tid, None))
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
        recovered_state = await _load_recovered_state(db, thread_id)
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

    async def event_generator():
        try:
            for payload in replay_snapshot:
                if await request.is_disconnected():
                    return
                event_type = payload.get("type", "message")
                yield _sse_line(event_type, payload)

            _stored = debate_store.get(thread_id)  # NB1: safe .get() — store is empty after restart
            if thread_id not in background_tasks and _stored is not None and _stored.status == "error":
                recovery_payload = {
                    "type": "error",
                    "error": "debate_recovery_required",
                    "detail": _stored.termination_reason or "recovery_required_after_restart",
                }
                yield f"event: error\ndata: {json.dumps(recovery_payload)}\n\n"
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(personal_queue.get(), timeout=20.0)
                    if payload is None:  # sentinel – debate finished
                        break
                    event_type = payload.get("type", "message")
                    yield _sse_line(event_type, dict(payload))
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            try:
                queue_list.remove(personal_queue)
            except ValueError:
                pass

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
    db: aiosqlite.Connection = Depends(get_db),
) -> DebateStatusResponse:
    """Return the live `DebateStatusResponse` for the given `thread_id`.  404 if unknown."""
    state = debate_store.get(thread_id)
    if state is None:
        state = await _load_recovered_state(db, thread_id)
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
    if state.status == "in_progress" and thread_id not in background_tasks:
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
    db: aiosqlite.Connection = Depends(get_db),
) -> FinalDecision:
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

    # Reject if a live background task is still running for this thread
    if state.status == "in_progress" and thread_id in background_tasks:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_in_progress",
                detail=f"Debate '{thread_id}' is still running. Cannot resume a live debate.",
            ).model_dump(),
        )

    # Transition back to in_progress for the resume run
    state.status = "in_progress"
    state.touch()
    debate_store[thread_id] = state
    await _persist_debate_state(state, settings.DATABASE_URL)

    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        on_state_change=lambda s: _persist_debate_state(s, settings.DATABASE_URL),
    )

    try:
        final_state, decision = await graph.resume(thread_id)
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
        state.status = "error"
        state.termination_reason = f"resume_failed:{error_type}"
        state.touch()
        debate_store[thread_id] = state
        await _persist_debate_state(state, settings.DATABASE_URL)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="resume_failed",
                detail=f"Resume failed ({error_type}): {exc}",
            ).model_dump(),
        ) from exc

    debate_store[thread_id] = final_state
    decision_store[thread_id] = decision
    app_metrics.increment_event("debate.resumed")
    await _persist_debate(final_state, decision, settings.DATABASE_URL)
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
    db: aiosqlite.Connection = Depends(get_db),
) -> HistoryListResponse:
    items_raw, total = await get_history(db, page=page, limit=limit, q=q)
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
            pdf_bytes = render_pdf(decision)
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
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def approve_debate(
    thread_id: str,
    request: Request,
    action: str = Query(
        default="approve",
        description="One of 'approve', 'override', or 'add_round'.",
    ),
    feedback: str = Query(default="", description="Human feedback text (used with 'override')."),
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict | FinalDecision:
    """Resume a HITL-interrupted debate with the user's approval decision."""
    from app.api.dependencies import get_knowledge_base, get_memory_store

    kb = get_knowledge_base()
    ms = get_memory_store()

    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        queue_list=all_queues.get(thread_id, []),
        replay_buffer=all_replays.get(thread_id, []),
        on_state_change=lambda s: _persist_debate_state(s, settings.DATABASE_URL),
        on_event=lambda payload, tid=thread_id: _persist_event(tid, payload, settings.DATABASE_URL),
        knowledge_base=kb,
        memory_store=ms,
    )
    try:
        final_state, decision = await graph.approve(thread_id, action=action, feedback=feedback)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(error="approve_failed", detail=str(exc)).model_dump(),
        ) from exc

    debate_store[thread_id] = final_state
    if decision is None and final_state.status == "awaiting_approval":
        app_metrics.increment_event("debate.awaiting_approval")
        await _persist_debate_state(final_state, settings.DATABASE_URL)
        audit_event(
            "debate.approve",
            outcome="pending",
            request=request,
            thread_id=thread_id,
            action_requested=action,
        )
        return {
            "thread_id": thread_id,
            "status": final_state.status,
            "current_round": final_state.current_round,
            "total_rounds": final_state.max_rounds,
        }

    decision_store[thread_id] = decision
    app_metrics.increment_event("debate.approved")
    await _persist_debate(final_state, decision, settings.DATABASE_URL)

    final_payload = json.loads(decision.model_dump_json())
    final_payload["type"] = "final_decision"
    for q in list(all_queues.get(thread_id, [])):
        q.put_nowait(final_payload)
        q.put_nowait(None)

    audit_event(
        "debate.approve",
        outcome="success",
        request=request,
        thread_id=thread_id,
        action_requested=action,
    )

    return decision


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
    query: str = Query(..., min_length=10, description="The decision question to simulate."),
    runs: int = Query(default=3, ge=2, le=5, description="Number of independent runs."),
    max_rounds: int = Query(default=3, ge=2, le=6),
    mode: DebateMode = Query(default="standard"),
    llm_client: LangChainProvider = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
):
    """Run N independent parallel debates for ``query`` and return a SimulationResult."""
    from app.services.simulation import run_simulation

    result = await run_simulation(
        query=query,
        runs=runs,
        max_rounds=max_rounds,
        mode=mode,
        llm_client=llm_client,
        settings=settings,
    )
    app_metrics.increment_event("debate.simulated")
    audit_event(
        "debate.simulate",
        outcome="success",
        request=request,
        runs=runs,
        mode=mode,
    )
    return result.model_dump()


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
    from app.api.dependencies import get_knowledge_base
    import tempfile, os, pathlib

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

    # Size limit from settings
    contents = await file.read()
    if len(contents) > settings.KB_MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.KB_MAX_FILE_MB} MB).",
        )

    # Write to a temp file, then ingest
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        # R1: kb.ingest is a coroutine — await it directly (not via asyncio.to_thread)
        chunks = await kb.ingest(tmp_path, {"source": file.filename or "upload"})
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
async def delete_knowledge_document(doc_name: str, request: Request):
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
async def clear_agent_memory(agent_name: str, request: Request):
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
    )


@router.post(
    "/llm-settings",
    response_model=LLMSettingsResponse,
    tags=["system"],
    summary="Switch the active LLM provider and model at runtime.",
)
async def update_llm_settings(body: LLMSettingsUpdate) -> LLMSettingsResponse:
    """
    Switches the global LLM singleton to the requested provider/model.

    - **Groq**: uses the server-side GROQ_API_KEY from .env (no user key needed).
    - **OpenAI / Anthropic**: ``api_key`` must be supplied by the caller and is
      held in memory only — never persisted to disk.
    """
    from app.core.config import settings as app_settings

    if body.provider == "groq":
        # Always fall back to the server-configured Groq key
        api_key = app_settings.GROQ_API_KEY
    else:
        api_key = body.api_key or ""

    reset_llm_client(provider=body.provider, api_key=api_key, model=body.model)
    logger.info(
        "llm_provider_switched_via_api",
        extra={"provider": body.provider, "model": body.model},
    )
    return LLMSettingsResponse(
        provider=body.provider,
        model=body.model,
        available_models=PROVIDER_MODELS,
        using_custom_key=(body.provider != "groq"),
    )

