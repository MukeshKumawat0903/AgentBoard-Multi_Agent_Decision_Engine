"""
API route definitions for AgentBoard.

All REST endpoints are defined here and included
via the main FastAPI application router.
"""

import asyncio
import json
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
from app.orchestrator.debate_graph import DebateGraph
from app.schemas.state import DebateState
from app.schemas.api_models import (
    AsyncDebateStartResponse,
    DebateStartRequest,
    DebateStatusResponse,
    ErrorResponse,
    HistoryItem,
    HistoryListResponse,
)
from app.schemas.final_decision import FinalDecision
from app.core.rate_limiter import limiter
from app.services.llm_client import LangChainProvider

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
) -> None:
    """Run the debate graph, persist results, then close all subscriber queues."""
    thread_id = debate_state.thread_id
    try:
        final_state, decision = await graph.run(
            debate_state.user_query,
            initial_state=debate_state,
        )
        debate_store[thread_id] = final_state
        decision_store[thread_id] = decision
        await _persist_debate(final_state, decision, database_url)
        # Emit final_decision event so SSE clients can render the panel
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
        # Send sentinel to all subscriber queues (signals end-of-stream)
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
    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        on_state_change=lambda state: _persist_debate_state(state, settings.DATABASE_URL),
    )
    logger.info("api_debate_start")
    state, decision = await graph.run(body.query, max_rounds=body.max_rounds)
    debate_store[state.thread_id] = state
    decision_store[state.thread_id] = decision
    await _persist_debate(state, decision, settings.DATABASE_URL)
    logger.info(
        "api_debate_complete",
        extra={"thread_id": state.thread_id, "termination_reason": state.termination_reason},
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
    # Pre-create state so we have a thread_id before the graph runs.
    # Create channels at the same time so no events are lost.
    debate_state = DebateState(
        user_query=body.query,
        max_rounds=(
            body.max_rounds
            if body.max_rounds is not None
            else settings.MAX_DEBATE_ROUNDS
        ),
    )
    thread_id = debate_state.thread_id
    queue_list: list = []
    replay_buffer: list = []
    all_queues[thread_id] = queue_list
    all_replays[thread_id] = replay_buffer
    debate_store[thread_id] = debate_state
    await _persist_debate_state(debate_state, settings.DATABASE_URL)

    graph = DebateGraph(
        llm_client=llm_client,
        settings=settings,
        queue_list=queue_list,
        replay_buffer=replay_buffer,
        on_state_change=lambda state: _persist_debate_state(state, settings.DATABASE_URL),
        on_event=lambda payload, tid=thread_id: _persist_event(tid, payload, settings.DATABASE_URL),
    )

    logger.info("api_async_debate_start", extra={"thread_id": thread_id})

    task = asyncio.create_task(
        _run_debate_background(
            graph, debate_state, debate_store, decision_store,
            all_queues, settings.DATABASE_URL,
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

    If the debate is already finished (in memory or DB), emits the
    final_decision event immediately and closes.
    """
    # Already done – fast path
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
    replay_snapshot = list(all_replays.get(thread_id, []))
    if not replay_snapshot:
        replay_snapshot = await get_debate_events(db, thread_id)

    async def event_generator():
        try:
            for payload in replay_snapshot:
                if await request.is_disconnected():
                    return
                event_type = payload.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

            if thread_id not in background_tasks and debate_store[thread_id].status == "error":
                recovery_payload = {
                    "type": "error",
                    "error": "debate_recovery_required",
                    "detail": debate_store[thread_id].termination_reason or "recovery_required_after_restart",
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
                    yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
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
    await _persist_debate(final_state, decision, settings.DATABASE_URL)
    logger.info(
        "api_debate_resume_complete",
        extra={"thread_id": thread_id, "termination_reason": final_state.termination_reason},
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
