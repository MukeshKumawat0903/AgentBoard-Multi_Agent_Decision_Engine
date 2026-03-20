"""
Abstract base class for all debate agents.

Each agent:
1. Receives the current DebateState
2. Constructs a role-specific prompt via abstract builder methods
3. Calls the LLM via LangChainProvider.ainvoke_structured()
4. Returns a validated AgentResponse or CritiqueResponse

The JSON parsing / retry boilerplate is gone. LangChain structured
output handles schema binding and validation, so _call_structured()
simply returns a typed Pydantic instance.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.services.llm_client import LangChainProvider

TModel = TypeVar("TModel", bound=BaseModel)


class AgentLLMOutput(BaseModel):
    """Minimal schema the LLM populates for a proposal or revision."""

    position: str = Field(description="The agent's stance or analysis (1-3 paragraphs).")
    reasoning: str = Field(description="Step-by-step reasoning supporting the position.")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions the agent is relying on.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence (0 = none, 1 = certain).",
    )


class CritiqueLLMOutput(BaseModel):
    """Minimal schema the LLM populates for a critique."""

    critique_points: list[str] = Field(
        description="Specific, actionable issues identified in the target's position.",
    )
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Overall severity of the critique's concerns.",
    )
    suggested_revision: str | None = Field(
        default=None,
        description="Optional concrete suggestion for how the target should revise.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence the critique points are valid.",
    )


class BaseAgent(ABC):
    """Abstract base class for all debate agents."""

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        llm_client: LangChainProvider,
    ) -> None:
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.logger = logging.getLogger(f"agentboard.agents.{name.lower()}")

    async def run(self, state: DebateState) -> AgentResponse:
        user_prompt = self._build_proposal_prompt(state)
        raw = await self._call_structured(
            AgentLLMOutput,
            "proposal",
            state.current_round,
            user_prompt,
        )
        return AgentResponse(
            agent_name=self.name,
            round_number=state.current_round,
            position=raw.position,
            reasoning=raw.reasoning,
            assumptions=raw.assumptions,
            confidence_score=raw.confidence_score,
        )

    async def critique(
        self,
        state: DebateState,
        target: AgentResponse,
    ) -> CritiqueResponse:
        user_prompt = self._build_critique_prompt(state, target)
        raw = await self._call_structured(
            CritiqueLLMOutput,
            "critique",
            state.current_round,
            user_prompt,
        )
        return CritiqueResponse(
            critic_agent=self.name,
            target_agent=target.agent_name,
            round_number=state.current_round,
            critique_points=raw.critique_points,
            severity=raw.severity,
            suggested_revision=raw.suggested_revision,
            confidence_score=raw.confidence_score,
        )

    async def revise(
        self,
        state: DebateState,
        critiques: list[CritiqueResponse],
    ) -> AgentResponse:
        user_prompt = self._build_revision_prompt(state, critiques)
        raw = await self._call_structured(
            AgentLLMOutput,
            "revision",
            state.current_round,
            user_prompt,
        )
        return AgentResponse(
            agent_name=self.name,
            round_number=state.current_round,
            position=raw.position,
            reasoning=raw.reasoning,
            assumptions=raw.assumptions,
            confidence_score=raw.confidence_score,
        )

    @abstractmethod
    def _build_proposal_prompt(self, state: DebateState) -> str:
        ...

    @abstractmethod
    def _build_critique_prompt(
        self,
        state: DebateState,
        target: AgentResponse,
    ) -> str:
        ...

    @abstractmethod
    def _build_revision_prompt(
        self,
        state: DebateState,
        critiques: list[CritiqueResponse],
    ) -> str:
        ...

    async def _call_structured(
        self,
        schema: type[TModel],
        action: str,
        round_number: int,
        user_prompt: str,
    ) -> TModel:
        prompt_chars = len(self.system_prompt) + len(user_prompt)
        self.logger.info(
            "llm_call_start",
            extra={
                "agent": self.name,
                "round": round_number,
                "action": action,
                "prompt_chars": prompt_chars,
            },
        )
        started = time.monotonic()
        try:
            result = await self.llm_client.ainvoke_structured(
                schema,
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            self.logger.error(
                "llm_call_failed",
                extra={
                    "agent": self.name,
                    "round": round_number,
                    "action": action,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise

        elapsed_ms = round((time.monotonic() - started) * 1000)
        self.logger.info(
            "llm_call_done",
            extra={
                "agent": self.name,
                "round": round_number,
                "action": action,
                "elapsed_ms": elapsed_ms,
            },
        )
        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} role={self.role!r}>"
