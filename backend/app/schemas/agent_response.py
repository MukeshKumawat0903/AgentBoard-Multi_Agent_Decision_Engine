"""
AgentResponse and CritiqueResponse schemas.

Defines the structured output contract for all agent interactions.
Every agent produces an AgentResponse for proposals/revisions and a
CritiqueResponse when evaluating another agent's position.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentResponse(BaseModel):
    """Structured output from a single agent in one debate round."""

    agent_name: str = Field(
        description="Name of the agent, e.g. 'Analyst', 'Risk', 'Strategy'."
    )
    round_number: int = Field(
        ge=1,
        description="Debate round this response belongs to.",
    )
    position: str = Field(
        min_length=1,
        description="The agent's stance or proposal (1–3 paragraphs).",
    )
    reasoning: str = Field(
        min_length=1,
        description="Step-by-step reasoning that supports the position.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions the agent is relying on.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent's self-assessed confidence (0 = none, 1 = certain).",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the response was generated.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_name": "Analyst",
                "round_number": 1,
                "position": "Based on the available data, Option A is the most viable path forward due to its superior cost-to-benefit ratio.",
                "reasoning": "Market analysis shows a 23% cost reduction with Option A. Historical precedent from Q2 2024 indicates similar conditions led to a 15% efficiency gain.",
                "assumptions": [
                    "Market conditions remain stable for the next 6 months",
                    "No significant regulatory changes are imminent",
                    "Current resource allocation remains constant",
                ],
                "confidence_score": 0.82,
            }
        }
    )


class CritiqueResponse(BaseModel):
    """Critique from one agent directed at another agent's position."""

    critic_agent: str = Field(
        description="Name of the agent performing the critique."
    )
    target_agent: str = Field(
        description="Name of the agent whose position is being critiqued."
    )
    round_number: int = Field(
        ge=1,
        description="Debate round this critique belongs to.",
    )
    critique_points: list[str] = Field(
        min_length=1,
        description="Specific, actionable issues identified in the target's position.",
    )
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Overall severity of the critique's concerns."
    )
    suggested_revision: str | None = Field(
        default=None,
        description="Optional concrete suggestion for how the target agent should revise.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Critic's confidence in the validity of this critique.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the critique was generated.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "critic_agent": "Risk",
                "target_agent": "Strategy",
                "round_number": 1,
                "critique_points": [
                    "The proposal assumes market stability but ignores geopolitical tail risks.",
                    "The 15% efficiency benchmark from Q2 2024 was under fundamentally different conditions.",
                    "No contingency plan is provided for supply chain disruption.",
                ],
                "severity": "high",
                "suggested_revision": "Incorporate a risk-adjusted scenario analysis and add a contingency branch for supply chain disruption.",
                "confidence_score": 0.78,
            }
        }
    )
