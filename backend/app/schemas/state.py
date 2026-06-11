"""
DebateState and DebateRound schemas.

DebateState is the **single source of truth** for an entire debate session.
All agents, the orchestrator, and the API layer read and write this object.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_response import AgentResponse, CritiqueResponse

# Valid status values for a DebateState
DebateStatus = Literal[
    "initialized",
    "in_progress",
    "converged",
    "max_rounds_reached",
    "awaiting_approval",
    "cancelled",  # user cancelled an in-flight async debate
    "error",
]

# Valid phase values for a DebateRound
DebatePhase = Literal["proposal", "critique", "revision", "convergence"]


class DebateRound(BaseModel):
    """
    Captures all data produced during one round of debate.

    A round has four sequential phases:
    1. proposal    – agents produce independent positions
    2. critique    – agents cross-examine each other
    3. revision    – agents update positions based on critique
    4. convergence – moderator measures agreement and decides whether to continue
    """

    round_number: int = Field(ge=1, description="1-based round index.")
    phase: DebatePhase = Field(
        default="proposal",
        description="Current phase within this round.",
    )
    agent_outputs: list[AgentResponse] = Field(
        default_factory=list,
        description="All agent proposals / revisions produced this round.",
    )
    critiques: list[CritiqueResponse] = Field(
        default_factory=list,
        description="All cross-examination critiques produced this round.",
    )
    tool_calls: list[dict] = Field(
        default_factory=list,
        description="Tool invocations made by agents this round (for the persisted trace).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "round_number": 1,
                "phase": "proposal",
                "agent_outputs": [],
                "critiques": [],
            }
        }
    )


class DebateState(BaseModel):
    """
    Complete, mutable state of a debate session.

    Design decisions:
    - Acts as the single source of truth passed to every component.
    - Each round appends a new DebateRound; previous rounds are immutable.
    - thread_id is a UUID auto-generated on creation for external tracking.
    - status drives API responses and convergence logic.
    """

    thread_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this debate session (UUID).",
    )
    user_query: str = Field(
        min_length=10,
        description="The original problem statement submitted by the user.",
    )
    current_round: int = Field(
        default=0,
        ge=0,
        description="The round currently being processed (0 = not yet started).",
    )
    max_rounds: int = Field(
        default=4,
        ge=2,
        le=8,
        description="Maximum number of debate rounds allowed.",
    )
    rounds: list[DebateRound] = Field(
        default_factory=list,
        description="Full ordered history of all rounds.",
    )
    agreement_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Latest consensus score produced by the Moderator (0–1).",
    )
    confidence_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Per-agent confidence from the most recent round, e.g. {'Analyst': 0.8}.",
    )
    termination_reason: str | None = Field(
        default=None,
        description="Human-readable explanation of why the debate ended.",
    )
    status: DebateStatus = Field(
        default="initialized",
        description="Lifecycle status of this debate session.",
    )
    # --- P3.1 Knowledge Base RAG ---
    use_knowledge_base: bool = Field(
        default=False,
        description="When True, agents retrieve context from the knowledge base.",
    )
    # --- P3.3 Agent Memory ---
    enable_agent_memory: bool = Field(
        default=False,
        description="When True, agents receive lessons from prior debates in their prompts.",
    )
    selected_agents: list[str] | None = Field(
        default=None,
        description="Optional per-debate agent list. When None, the enabled default set is used.",
    )
    domain_pack: str | None = Field(
        default=None,
        description="Optional domain pack ID that determined the selected agent set.",
    )
    # --- P4.1 Human-in-the-Loop ---
    human_feedback: str | None = Field(
        default=None,
        description="Optional human feedback injected during a HITL override.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the debate was created.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the last state update.",
    )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def current_round_data(self) -> DebateRound | None:
        """Return the DebateRound for the current round, or None if not started."""
        for r in self.rounds:
            if r.round_number == self.current_round:
                return r
        return None

    def latest_outputs(self) -> list[AgentResponse]:
        """Return agent outputs from the most recent round, or empty list."""
        if not self.rounds:
            return []
        return self.rounds[-1].agent_outputs

    def latest_critiques(self) -> list[CritiqueResponse]:
        """Return critiques from the most recent round, or empty list."""
        if not self.rounds:
            return []
        return self.rounds[-1].critiques

    def touch(self) -> None:
        """Update the updated_at timestamp to now (call after every mutation)."""
        self.updated_at = datetime.now(UTC)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "user_query": "Should our company expand into the Asian market in Q3?",
                "current_round": 0,
                "max_rounds": 4,
                "rounds": [],
                "agreement_score": 0.0,
                "confidence_scores": {},
                "termination_reason": None,
                "status": "initialized",
            }
        }
    )
