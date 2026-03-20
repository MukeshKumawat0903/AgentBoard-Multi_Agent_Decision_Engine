"""
API request and response models.

All REST endpoint payloads are defined here as Pydantic v2 models,
separate from the domain schemas to keep API contracts clean.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.state import DebateRound


__all__ = [
    "DebateMode",
    "DebateStartRequest",
    "resolve_debate_config",
]


# ---------------------------------------------------------------------------
# Debate mode presets
# ---------------------------------------------------------------------------

DebateMode = Literal["quick", "standard", "thorough"]

_MODE_PRESETS: dict[str, dict] = {
    "quick":    {"max_rounds": 2, "consensus_threshold": 0.60, "skip_critique_phase": True},
    "standard": {"max_rounds": 4, "consensus_threshold": 0.75, "skip_critique_phase": False},
    "thorough": {"max_rounds": 6, "consensus_threshold": 0.85, "skip_critique_phase": False},
}


def resolve_debate_config(
    mode: DebateMode | None,
    max_rounds: int | None,
    consensus_threshold: float | None,
    skip_critique_phase: bool | None,
    default_max_rounds: int,
    default_threshold: float,
) -> tuple[int, float, bool]:
    """
    Return (max_rounds, consensus_threshold, skip_critique_phase) after merging
    mode presets with any explicit overrides.  Explicit values always win.
    """
    base = _MODE_PRESETS.get(mode or "standard", _MODE_PRESETS["standard"])
    resolved_rounds = max_rounds if max_rounds is not None else base["max_rounds"]
    resolved_threshold = consensus_threshold if consensus_threshold is not None else base["consensus_threshold"]
    resolved_skip = skip_critique_phase if skip_critique_phase is not None else base["skip_critique_phase"]
    return resolved_rounds, resolved_threshold, resolved_skip


class DebateStartRequest(BaseModel):
    """Request body for POST /debate/start."""

    query: str = Field(
        min_length=10,
        max_length=5000,
        description="The problem or question the agents should debate.",
    )
    mode: DebateMode | None = Field(
        default=None,
        description=(
            "Preset debate mode: 'quick' (2 rounds, no critiques), "
            "'standard' (4 rounds), 'thorough' (6 rounds). "
            "Explicit max_rounds/consensus_threshold override the preset."
        ),
    )
    max_rounds: int | None = Field(
        default=None,
        ge=2,
        le=8,
        description="Maximum number of debate rounds (2–8). Overrides mode preset.",
    )
    consensus_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Agreement score (0–1) at which debate stops early. Overrides mode preset.",
    )
    skip_critique_phase: bool | None = Field(
        default=None,
        description="Skip critique & revision phases each round. Overrides mode preset.",
    )
    agents: list[str] | None = Field(
        default=None,
        description="Optional subset of agent names to use. Defaults to all enabled agents.",
    )
    use_knowledge_base: bool = Field(
        default=False,
        description="When True, agents retrieve context from the knowledge base before proposing.",
    )
    enable_agent_memory: bool = Field(
        default=False,
        description="When True, agents receive lessons from past debates at the start of this debate.",
    )
    domain_pack: str | None = Field(
        default=None,
        description="Optional domain pack ID (e.g. 'finance', 'engineering', 'legal', 'healthcare'). Overrides agents list.",
    )
    supervised: bool = Field(
        default=False,
        description="When True, the debate pauses after each convergence phase for human approval.",
    )

    @model_validator(mode="after")
    def apply_mode_defaults(self) -> "DebateStartRequest":
        """Materialize preset defaults so the request model matches API expectations."""
        resolved_rounds, resolved_threshold, resolved_skip = resolve_debate_config(
            mode=self.mode,
            max_rounds=self.max_rounds,
            consensus_threshold=self.consensus_threshold,
            skip_critique_phase=self.skip_critique_phase,
            default_max_rounds=_MODE_PRESETS["standard"]["max_rounds"],
            default_threshold=_MODE_PRESETS["standard"]["consensus_threshold"],
        )
        self.max_rounds = resolved_rounds
        self.consensus_threshold = resolved_threshold
        self.skip_critique_phase = resolved_skip
        if self.mode is None:
            self.mode = "standard"
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Should our company expand into the Asian market in Q3?",
                "mode": "standard",
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
