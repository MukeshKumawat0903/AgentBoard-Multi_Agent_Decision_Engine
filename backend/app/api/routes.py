"""
API route definitions for AgentBoard.

All REST endpoints are defined here and included
via the main FastAPI application router.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_debate_store,
    get_decision_store,
    get_groq_client,
    get_settings,
)
from app.core.config import Settings
from app.orchestrator.debate_controller import DebateController
from app.schemas.api_models import (
    DebateStartRequest,
    DebateStatusResponse,
    ErrorResponse,
)
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient

router = APIRouter()
logger = logging.getLogger("agentboard.api")


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
    logger.info(
        "api_debate_complete",
        extra={
            "thread_id": state.thread_id,
            "termination_reason": state.termination_reason,
        },
    )
    return decision


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
) -> FinalDecision:
    """
    Return the `FinalDecision` for `thread_id`.

    - 404 if the thread is unknown.
    - 409 if the debate is still in progress (decision not yet available).
    """
    if thread_id not in debate_store:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="debate_not_found",
                detail=f"No debate session found with thread_id '{thread_id}'.",
            ).model_dump(),
        )
    if thread_id not in decision_store:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="debate_in_progress",
                detail=f"Debate '{thread_id}' has not yet produced a final decision.",
            ).model_dump(),
        )
    return decision_store[thread_id]
