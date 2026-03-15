"""
API request and response models.

All REST endpoint payloads are defined here as Pydantic v2 models,
separate from the domain schemas to keep API contracts clean.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.state import DebateRound


class DebateStartRequest(BaseModel):
    """Request body for POST /debate/start."""

    query: str = Field(
        min_length=10,
        max_length=5000,
        description="The problem or question the agents should debate.",
    )
    max_rounds: int = Field(
        default=4,
        ge=2,
        le=8,
        description="Maximum number of debate rounds (2–8, default 4).",
    )
    agents: list[str] | None = Field(
        default=None,
        description="Optional subset of agent names to use. Defaults to all 4 agents + moderator.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Should our company expand into the Asian market in Q3?",
                "max_rounds": 4,
                "agents": None,
            }
        }
    )


class DebateStartResponse(BaseModel):
    """
    Response for POST /debate/start (V1 – synchronous).

    In V1 the full FinalDecision is returned directly.
    This lightweight response is reserved for a future async V2 endpoint
    that returns immediately while the debate runs in the background.
    """

    thread_id: str = Field(description="UUID of the debate session.")
    status: str = Field(description="Initial debate status.")
    message: str = Field(description="Human-readable confirmation message.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "status": "in_progress",
                "message": "Debate started successfully. Poll GET /debate/{thread_id} for status.",
            }
        }
    )


class DebateStatusResponse(BaseModel):
    """Response for GET /debate/{thread_id}."""

    thread_id: str = Field(description="UUID of the debate session.")
    status: str = Field(description="Current lifecycle status of the debate.")
    current_round: int = Field(description="Round currently being processed (0 = not yet started).")
    total_rounds: int = Field(description="Maximum rounds allowed for this debate.")
    agreement_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Latest consensus score (0–1).",
    )
    rounds: list[DebateRound] = Field(
        description="All rounds completed so far.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "status": "in_progress",
                "current_round": 2,
                "total_rounds": 4,
                "agreement_score": 0.61,
                "rounds": [],
            }
        }
    )


class ErrorResponse(BaseModel):
    """Standard error response used for all 4xx and 5xx responses."""

    error: str = Field(description="Short error code or title.")
    detail: str | None = Field(
        default=None,
        description="Optional detailed description of the error.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "debate_not_found",
                "detail": "No debate session found with thread_id '3fa85f64-5717-4562-b3fc-2c963f66afa6'.",
            }
        }
    )


# ---------------------------------------------------------------------------
# Async / streaming models
# ---------------------------------------------------------------------------


class AsyncDebateStartResponse(BaseModel):
    """Response for POST /debate/start-async – debate runs in the background."""

    thread_id: str = Field(description="UUID of the debate session.")
    status: str = Field(description="Initial status ('initialized').")
    stream_url: str = Field(description="SSE endpoint to subscribe to live events.")


# ---------------------------------------------------------------------------
# History / comparison models
# ---------------------------------------------------------------------------


class HistoryItem(BaseModel):
    """Lightweight summary row returned by GET /history."""

    thread_id: str
    user_query: str
    created_at: str
    status: str
    total_rounds: int
    agreement_score: float
    termination_reason: str


class HistoryListResponse(BaseModel):
    """Paginated list of completed debates."""

    items: list[HistoryItem]
    total: int
    page: int
    limit: int
