"""
Abstract base class for all debate agents.

Each agent:
1. Receives the current DebateState
2. Constructs a role-specific prompt
3. Calls the LLM via GroqClient
4. Returns a validated AgentResponse or CritiqueResponse

Subclasses MUST implement:
- _build_proposal_prompt(state) -> str
- _build_critique_prompt(state, target) -> str
- _build_revision_prompt(state, critiques) -> str
"""

import logging
import time
from abc import ABC, abstractmethod

from pydantic import ValidationError

from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient
from app.utils.exceptions import LLMResponseError


class BaseAgent(ABC):
    """
    Abstract base class for all debate agents.

    Subclasses control prompt construction; this class handles all
    LLM calling, response parsing, logging, and error translation so
    every agent follows an identical contract.

    Lifecycle per round
    -------------------
    1. Orchestrator calls ``run(state)``         → agent proposes a position
    2. Orchestrator calls ``critique(state, t)`` → agent critiques another
    3. Orchestrator calls ``revise(state, cs)``  → agent revises based on critiques

    All three methods log: agent name, round, action, prompt_chars,
    elapsed_ms, confidence_score (or parse error).
    """

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        llm_client: GroqClient,
    ) -> None:
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.logger = logging.getLogger(f"agentboard.agents.{name.lower()}")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self, state: DebateState) -> AgentResponse:
        """Generate a proposal for the current debate round."""
        user_prompt = self._build_proposal_prompt(state)
        raw = await self._call_llm("proposal", state.current_round, user_prompt)
        return self._parse_response(raw, state.current_round)

    async def critique(
        self, state: DebateState, target: AgentResponse
    ) -> CritiqueResponse:
        """Critique another agent's position."""
        user_prompt = self._build_critique_prompt(state, target)
        raw = await self._call_llm("critique", state.current_round, user_prompt)
        return self._parse_critique(raw, target.agent_name, state.current_round)

    async def revise(
        self, state: DebateState, critiques: list[CritiqueResponse]
    ) -> AgentResponse:
        """Revise own position based on the critiques received this round."""
        user_prompt = self._build_revision_prompt(state, critiques)
        raw = await self._call_llm("revision", state.current_round, user_prompt)
        return self._parse_response(raw, state.current_round)

    # ------------------------------------------------------------------
    # Abstract prompt builders – subclasses MUST implement
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_proposal_prompt(self, state: DebateState) -> str:
        """Build the user-turn prompt for a fresh proposal."""
        ...

    @abstractmethod
    def _build_critique_prompt(
        self, state: DebateState, target: AgentResponse
    ) -> str:
        """Build the user-turn prompt used when critiquing another agent."""
        ...

    @abstractmethod
    def _build_revision_prompt(
        self, state: DebateState, critiques: list[CritiqueResponse]
    ) -> str:
        """Build the user-turn prompt used when revising based on critiques."""
        ...

    # ------------------------------------------------------------------
    # LLM calling + parsing (shared, not overrideable)
    # ------------------------------------------------------------------

    async def _call_llm(
        self, action: str, round_number: int, user_prompt: str
    ) -> dict:
        """
        Call the LLM and return the parsed JSON dict.

        Logs agent name, round, action, prompt_chars, and elapsed_ms.
        Re-raises any LLM* exceptions from GroqClient unchanged.
        """
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
        t0 = time.monotonic()
        raw = await self.llm_client.chat_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
        )
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        self.logger.info(
            "llm_call_done",
            extra={
                "agent": self.name,
                "round": round_number,
                "action": action,
                "elapsed_ms": elapsed_ms,
            },
        )
        return raw

    def _parse_response(self, raw: dict, round_number: int) -> AgentResponse:
        """
        Validate *raw* LLM dict into an ``AgentResponse``.

        Injects ``agent_name`` and ``round_number`` from the calling
        context so agents don't have to repeat them in the prompt.
        Raises ``LLMResponseError`` on schema violation.
        """
        raw.setdefault("agent_name", self.name)
        raw.setdefault("round_number", round_number)
        try:
            response = AgentResponse.model_validate(raw)
        except (ValidationError, Exception) as exc:
            self.logger.error(
                "parse_response_failed",
                extra={
                    "agent": self.name,
                    "round": round_number,
                    "raw_keys": list(raw.keys()),
                    "error": str(exc),
                },
            )
            raise LLMResponseError(
                f"[{self.name}] AgentResponse parse failed: {exc}\nRaw keys: {list(raw.keys())}"
            ) from exc
        self.logger.debug(
            "parse_response_ok",
            extra={
                "agent": self.name,
                "round": round_number,
                "confidence": response.confidence_score,
            },
        )
        return response

    def _parse_critique(
        self, raw: dict, target_agent: str, round_number: int
    ) -> CritiqueResponse:
        """
        Validate *raw* LLM dict into a ``CritiqueResponse``.

        Injects ``critic_agent``, ``target_agent``, and ``round_number``
        from the calling context.
        Raises ``LLMResponseError`` on schema violation.
        """
        raw.setdefault("critic_agent", self.name)
        raw.setdefault("target_agent", target_agent)
        raw.setdefault("round_number", round_number)
        try:
            critique = CritiqueResponse.model_validate(raw)
        except (ValidationError, Exception) as exc:
            self.logger.error(
                "parse_critique_failed",
                extra={
                    "agent": self.name,
                    "round": round_number,
                    "target": target_agent,
                    "raw_keys": list(raw.keys()),
                    "error": str(exc),
                },
            )
            raise LLMResponseError(
                f"[{self.name}] CritiqueResponse parse failed: {exc}\nRaw keys: {list(raw.keys())}"
            ) from exc
        self.logger.debug(
            "parse_critique_ok",
            extra={
                "agent": self.name,
                "round": round_number,
                "target": target_agent,
                "confidence": critique.confidence_score,
            },
        )
        return critique

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} role={self.role!r}>"
