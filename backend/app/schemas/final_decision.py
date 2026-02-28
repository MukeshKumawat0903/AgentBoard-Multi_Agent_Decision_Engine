"""
FinalDecision schema.

The structured, auditable output produced by the Moderator Agent
once the debate has converged or reached the maximum round limit.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.state import DebateRound


class FinalDecision(BaseModel):
    """
    The converged output of a completed multi-agent debate session.

    Contains the decision itself, supporting rationale, risk flags,
    alternatives, and the full debate trace for auditability.
    """

    thread_id: str = Field(
        description="Unique identifier of the debate session that produced this decision."
    )
    decision: str = Field(
        min_length=1,
        description="Clear, actionable decision statement.",
    )
    rationale_summary: str = Field(
        min_length=1,
        description="Concise explanation of why this decision was chosen over alternatives.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence-weighted aggregate across all agents' final positions.",
    )
    agreement_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Degree of consensus reached by the agents (0 = no agreement, 1 = full agreement).",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Key risks identified by the Risk Agent and surfaced in debate.",
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="Other viable options considered but ultimately not chosen.",
    )
    dissenting_opinions: list[str] = Field(
        default_factory=list,
        description="Summaries of positions that diverged from the final decision.",
    )
    debate_trace: list[DebateRound] = Field(
        default_factory=list,
        description="Complete ordered history of all debate rounds – the full audit trail.",
    )
    total_rounds: int = Field(
        ge=1,
        description="Total number of debate rounds that were completed.",
    )
    termination_reason: str = Field(
        description="Why the debate ended, e.g. 'consensus_reached' or 'max_rounds_reached'.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the final decision was produced.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "decision": "Proceed with a phased expansion into the Southeast Asian market starting Q3, with an initial pilot in Singapore and Malaysia.",
                "rationale_summary": "All agents reached 87% agreement after 3 rounds. The Analyst confirmed strong market signals. The Risk Agent's concerns about regulatory complexity were addressed by limiting the pilot to 2 lower-risk markets.",
                "confidence_score": 0.85,
                "agreement_score": 0.87,
                "risk_flags": [
                    "Regulatory complexity varies significantly across ASEAN markets",
                    "Currency volatility in Q3 may impact unit economics",
                    "Talent acquisition in new markets may take 3–6 months longer than projected",
                ],
                "alternatives": [
                    "Full 5-country rollout – rejected due to operational risk",
                    "Delay expansion to Q1 next year – rejected due to competitive pressure",
                ],
                "dissenting_opinions": [],
                "debate_trace": [],
                "total_rounds": 3,
                "termination_reason": "consensus_reached",
            }
        }
    )
