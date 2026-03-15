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
    get_db,
    get_debate_store,
    get_decision_store,
    get_event_queues,
    get_event_replays,
    get_groq_client,
    get_settings,
)
from app.core.config import Settings
from app.db.crud import get_decision_json, get_history, save_decision, upsert_debate
from app.orchestrator.debate_controller import DebateController
from app.schemas.api_models import (
    AsyncDebateStartResponse,
    DebateStartRequest,
    DebateStatusResponse,
    ErrorResponse,
    HistoryItem,
    HistoryListResponse,
)
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient

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


async def _run_debate_background(
    controller: DebateController,
    state: DebateState,
    debate_store: dict,
    decision_store: dict,
    all_queues: dict,
    database_url: str,
) -> None:
    """Run the debate, persist results, then close all subscriber queues."""
    try:
        decision = await controller.execute()
        decision_store[state.thread_id] = decision
        await _persist_debate(state, decision, database_url)
        # Emit final_decision event so SSE clients can render the panel
        final_payload = json.loads(decision.model_dump_json())
        final_payload["type"] = "final_decision"
        queue_list = all_queues.get(state.thread_id, [])
        for q in list(queue_list):
            q.put_nowait(final_payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("background_debate_failed", extra={"error": str(exc)})
        state.status = "error"
    finally:
        # Send sentinel to all subscriber queues
        queue_list = all_queues.get(state.thread_id, [])
        for q in list(queue_list):
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
async def start_debate(
    request: DebateStartRequest,
    llm_client: GroqClient = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
) -> FinalDecision:
    """
    Run a complete multi-agent debate synchronously and return the
    `FinalDecision`.  The client blocks until the debate finishes.

    V2 will add an async variant (`/debate/start-async`) that returns
    a `thread_id` immediately and lets the client poll for results.
    """
    controller = DebateController(llm_client=llm_client, settings=settings)
    state = await controller.initialize_state(
        request.query, max_rounds=request.max_rounds
    )
    debate_store[state.thread_id] = state
    logger.info("api_debate_start", extra={"thread_id": state.thread_id})

    try:
        decision = await controller.execute()
    except Exception:
        state.status = "error"
        raise

    decision_store[state.thread_id] = decision
    asyncio.create_task(_persist_debate(state, decision, settings.DATABASE_URL))
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
async def start_debate_async(
    request: DebateStartRequest,
    llm_client: GroqClient = Depends(get_groq_client),
    settings: Settings = Depends(get_settings),
    debate_store: dict[str, DebateState] = Depends(get_debate_store),
    decision_store: dict[str, FinalDecision] = Depends(get_decision_store),
    all_queues: dict = Depends(get_event_queues),
    all_replays: dict = Depends(get_event_replays),
) -> AsyncDebateStartResponse:
    # Create channels BEFORE constructing the controller so no events are lost
    queue_list: list = []
    replay_buffer: list = []

    controller = DebateController(
        llm_client=llm_client,
        settings=settings,
        queue_list=queue_list,
        replay_buffer=replay_buffer,
    )
    state = await controller.initialize_state(
        request.query, max_rounds=request.max_rounds
    )
    all_queues[state.thread_id] = queue_list
    all_replays[state.thread_id] = replay_buffer
    debate_store[state.thread_id] = state

    logger.info("api_async_debate_start", extra={"thread_id": state.thread_id})

    asyncio.create_task(
        _run_debate_background(
            controller, state, debate_store, decision_store,
            all_queues, settings.DATABASE_URL,
        )
    )
    return AsyncDebateStartResponse(
        thread_id=state.thread_id,
        status="initialized",
        stream_url=f"/debate/{state.thread_id}/stream",
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

    async def event_generator():
        try:
            for payload in replay_snapshot:
                if await request.is_disconnected():
                    return
                event_type = payload.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

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
) -> DebateStatusResponse:
    """Return the live `DebateStatusResponse` for the given `thread_id`.  404 if unknown."""
    state = debate_store.get(thread_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="debate_not_found",
                detail=f"No debate session found with thread_id '{thread_id}'.",
            ).model_dump(),
        )
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
