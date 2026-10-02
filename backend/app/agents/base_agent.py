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
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, ClassVar, Literal, TypeVar

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.agent_response import AgentResponse, CritiqueReply, CritiqueResponse, Stance
from app.schemas.state import DebateState
from app.services.llm_client import LangChainProvider

if TYPE_CHECKING:
    from app.services.agent_memory import AgentMemoryStore
    from app.services.retriever import KnowledgeBase

TModel = TypeVar("TModel", bound=BaseModel)

STANCE_DESCRIPTION = (
    "Your verdict on the proposal on the table: support, oppose, or "
    "conditional (support only if specific conditions are met). "
    "Use abstain only if your role does not make recommendations."
)
CRITIQUE_REPLY_INSTRUCTION = (
    "For each critique above, add one entry to `critique_replies` with the critic's "
    "name and a status: `addressed` (you changed your position), `rebutted` (it's "
    "wrong, say why in one line in `note`), or `unaddressed`. A `critical` critique "
    "needs a real change, not only a rebuttal."
)
# Stance anchor before the Moderator has named a leading proposal.
_DEFAULT_PROPOSAL = (
    "the course of action the problem statement asks about "
    "(support = yes, go ahead; oppose = no)."
)


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
    # Required so structured output always fills it; drives the stance-based
    # agreement score (see services/consensus.compute_stance_agreement).
    stance: Stance = Field(description=STANCE_DESCRIPTION)
    # Proposals leave it empty; revisions answer each critique received, which
    # decides whether the critique is still open (count_open_disagreements).
    critique_replies: list[CritiqueReply] = Field(
        default_factory=list,
        description=(
            "Revisions only: one entry per critique you received, with the critic's "
            "name and whether you addressed, rebutted or left it unaddressed."
        ),
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

        # --- P3.1 Knowledge Base RAG (set by DebateGraph after construction) ---
        self.knowledge_base: KnowledgeBase | None = None

        # --- P3.3 Agent Memory (set by DebateGraph after construction) ---
        self.memory_store: AgentMemoryStore | None = None

        # --- P3.2 Allowed tools (set by registry from AgentConfig.allowed_tools) ---
        self.allowed_tools: list[str] = []
        # Emit callback injected by DebateGraph so tool events propagate as SSE
        self.emit_callback: Callable[[str, dict], None] | None = None
        # Maximum tool invocations per run() / revise() call
        self.max_tool_calls_per_round: int = settings.MAX_TOOL_CALLS_PER_ROUND
        # Cache of tool outputs keyed by (tool_name, input) so an agent does not
        # re-run the same search across its proposal and revision calls.
        self._tool_cache: dict[tuple[str, str], str] = {}
        # Tool calls made during the most recent run()/revise(), so the node can
        # record them on the round for the persisted trace.
        self._last_tool_calls: list[dict] = []

        # B7 Fix: per-agent LLM sampling temperature and retry budget, populated
        # by AgentRegistry.get() from AgentConfig so they have real effect.
        self.temperature: float = 0.3
        self.max_retries: int = 2

    # Schema the LLM fills for proposals and revisions; Ethics-class agents add a veto.
    output_schema: ClassVar[type[AgentLLMOutput]] = AgentLLMOutput
    # Role-specific rule added to the stance instruction (e.g. the Analyst abstains).
    stance_guidance: ClassVar[str] = ""

    def _to_response(
        self,
        raw: AgentLLMOutput,
        round_number: int,
        received_critiques: Sequence[CritiqueResponse] = (),
    ) -> AgentResponse:
        veto = bool(getattr(raw, "veto", False))
        stance: Stance | None = getattr(raw, "stance", None)
        # A veto is a "no": an agent cannot veto a proposal and back it in the same breath.
        if veto and stance in ("support", "conditional"):
            self.logger.info(
                "stance_coerced_by_veto",
                extra={"agent": self.name, "round": round_number, "stance": stance},
            )
            stance = "oppose"
        return AgentResponse(
            agent_name=self.name,
            round_number=round_number,
            position=raw.position,
            reasoning=raw.reasoning,
            assumptions=raw.assumptions,
            confidence_score=raw.confidence_score,
            veto=veto,
            veto_reason=getattr(raw, "veto_reason", None) if veto else None,
            stance=stance,
            critique_replies=self._sanitize_replies(
                getattr(raw, "critique_replies", None) or [], received_critiques
            ),
        )

    def _sanitize_replies(
        self,
        replies: list[CritiqueReply],
        received_critiques: Sequence[CritiqueResponse],
    ) -> list[CritiqueReply]:
        """Keep only replies to critics who actually critiqued this agent, one per critic.

        A proposal received no critiques, so it keeps none: otherwise a proposal left
        in place by a failed revision could close a critique with an invented reply.
        Names match case-insensitively and are stored as the critic's real name; when
        a critic is answered twice, the last answer wins.
        """
        critics = {c.critic_agent.strip().lower(): c.critic_agent for c in received_critiques}
        kept: dict[str, CritiqueReply] = {}
        for reply in replies:
            critic = critics.get(reply.critic_agent.strip().lower())
            if critic is None:
                continue
            kept[critic] = reply.model_copy(update={"critic_agent": critic})
        dropped = len(replies) - len(kept)
        if dropped:
            self.logger.info(
                "critique_replies_dropped",
                extra={"agent": self.name, "dropped": dropped},
            )
        return list(kept.values())

    @staticmethod
    def _proposal_on_the_table(state: DebateState) -> str | None:
        """The Moderator's leading proposal from the previous round, if it gave one."""
        for round_data in state.rounds:
            if round_data.round_number == state.current_round - 1:
                return (round_data.leading_proposal or "").strip() or None
        return None

    def _stance_instruction(self, state: DebateState) -> str:
        """Instruction appended to proposal/revision prompts telling the agent what
        its ``stance`` is about and how to set it.

        Round 1 (or when the Moderator gave no leading proposal): the decision the
        problem statement asks for, so "Should we expand?" → support = yes.
        Round 2+: the Moderator's leading proposal from the previous round.
        """
        proposal = self._proposal_on_the_table(state) or _DEFAULT_PROPOSAL
        lines = [
            f"Proposal on the table: {proposal}",
            f"Set `stance` toward this proposal. {STANCE_DESCRIPTION}",
        ]
        if self.stance_guidance:
            lines.append(self.stance_guidance)
        return "\n\n---\n" + "\n".join(lines)

    @staticmethod
    def _critique_reply_instruction(critiques: list[CritiqueResponse]) -> str:
        """Instruction appended to revision prompts asking for one reply per critic."""
        if not critiques:
            return ""
        critics = ", ".join(dict.fromkeys(c.critic_agent for c in critiques))
        return f"\n\n{CRITIQUE_REPLY_INSTRUCTION}\nCritics to answer: {critics}."

    async def run(self, state: DebateState) -> AgentResponse:
        user_prompt = self._build_proposal_prompt(state) + self._stance_instruction(state)
        # P3.1: inject knowledge-base context into the proposal prompt
        if self.knowledge_base is not None and state.use_knowledge_base:
            user_prompt = await self._enrich_with_kb(user_prompt, state.user_query)
        # P3.2: run tools and append their output
        if self.allowed_tools:
            user_prompt = await self._run_tools(user_prompt, state.user_query)
        # P3.3: inject agent memory into system prompt for this call
        system_prompt = await self._build_system_prompt(state)
        raw = await self._call_structured(
            self.output_schema,
            "proposal",
            state.current_round,
            user_prompt,
            system_prompt=system_prompt,
        )
        return self._to_response(raw, state.current_round)

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
        user_prompt = (
            self._build_revision_prompt(state, critiques)
            + self._critique_reply_instruction(critiques)
            + self._stance_instruction(state)
        )
        # P3.1: inject KB context into revisions as well
        if self.knowledge_base is not None and state.use_knowledge_base:
            user_prompt = await self._enrich_with_kb(user_prompt, state.user_query)
        # P3.2: re-run tools so revisions can incorporate fresh tool output
        if self.allowed_tools:
            user_prompt = await self._run_tools(user_prompt, state.user_query)
        system_prompt = await self._build_system_prompt(state)
        raw = await self._call_structured(
            self.output_schema,
            "revision",
            state.current_round,
            user_prompt,
            system_prompt=system_prompt,
        )
        return self._to_response(raw, state.current_round, critiques)

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

    # ------------------------------------------------------------------
    # P3.1 Knowledge-base enrichment
    # ------------------------------------------------------------------

    async def _enrich_with_kb(self, user_prompt: str, query: str) -> str:
        """Retrieve relevant hits from KB and append to user_prompt with source attribution (R6)."""
        try:
            hits = await self.knowledge_base.retrieve(query)  # type: ignore[union-attr]
            if hits:
                parts = [
                    f"[Source: {h['source']} · {h['score']}]\n{h['text']}"
                    for h in hits
                ]
                context = "\n\n".join(parts)
                return f"{user_prompt}\n\n---\nRelevant context from knowledge base:\n{context}"
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "kb_retrieval_failed",
                extra={"agent": self.name, "error": str(exc)},
            )
        return user_prompt

    # ------------------------------------------------------------------
    # P3.2 Tool execution
    # ------------------------------------------------------------------

    async def _run_tools(self, user_prompt: str, query: str = "") -> str:
        """Run allowed tools (capped at max_tool_calls_per_round) and append outputs."""
        import asyncio

        from app.agents.tools import TOOL_REGISTRY

        tool_outputs: list[str] = []
        calls_made = 0
        self._last_tool_calls = []
        for tool_name in self.allowed_tools:
            if calls_made >= self.max_tool_calls_per_round:
                self.logger.info(
                    "tool_cap_reached",
                    extra={"agent": self.name, "cap": self.max_tool_calls_per_round},
                )
                break
            tool = TOOL_REGISTRY.get(tool_name)
            if tool is None:
                continue
            try:
                # NB7: use the actual debate query, not a truncated prompt preamble
                tool_input = "" if tool_name == "get_current_date" else (query or user_prompt[:200])
                # Skip a web search when the input is too short to be meaningful.
                if tool_name == "web_search" and len(tool_input.strip()) < 5:
                    continue
                cache_key = (tool_name, tool_input)
                if cache_key in self._tool_cache:
                    output_str = self._tool_cache[cache_key]
                else:
                    output = await asyncio.to_thread(tool.run, tool_input)
                    output_str = str(output)
                    self._tool_cache[cache_key] = output_str
                calls_made += 1
                tool_outputs.append(f"[{tool_name}]: {output_str}")
                self.logger.info(
                    "tool_called",
                    extra={"agent": self.name, "tool": tool_name, "output_snippet": output_str[:100]},
                )
                record = {
                    "agent_name": self.name,
                    "tool_name": tool_name,
                    "input": tool_input,
                    "output_snippet": output_str[:200],
                }
                # Keep a copy on the agent so the node can record it on the round.
                self._last_tool_calls.append(record)
                # Emit SSE event so the frontend can surface tool activity
                if self.emit_callback is not None:
                    self.emit_callback("tool_called", record)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "tool_call_failed",
                    extra={"agent": self.name, "tool": tool_name, "error": str(exc)},
                )
        if tool_outputs:
            return f"{user_prompt}\n\n---\nTool outputs:\n" + "\n".join(tool_outputs)
        return user_prompt

    # ------------------------------------------------------------------
    # P3.3 Memory-enriched system prompt
    # ------------------------------------------------------------------

    async def _build_system_prompt(self, state: DebateState) -> str:
        """Return the system prompt, optionally prepended with memory lessons."""
        if self.memory_store is None or not state.enable_agent_memory:
            return self.system_prompt
        try:
            lessons = await self.memory_store.get_recent_memory(self.name, limit=5)
            if lessons:
                memory_block = "Lessons from your past debates:\n" + "\n".join(f"- {lesson}" for lesson in lessons)
                return f"{memory_block}\n\n{self.system_prompt}"
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "memory_inject_failed",
                extra={"agent": self.name, "error": str(exc)},
            )
        return self.system_prompt

    async def _call_structured(
        self,
        schema: type[TModel],
        action: str,
        round_number: int,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> TModel:
        effective_system = system_prompt if system_prompt is not None else self.system_prompt
        prompt_chars = len(effective_system) + len(user_prompt)
        self.logger.info(
            "llm_call_start",
            extra={
                "agent": self.name,
                "round": round_number,
                "action": action,
                "prompt_chars": prompt_chars,
                "provider": self.llm_client.provider,
                "model": self.llm_client.model,
            },
        )
        started = time.monotonic()
        try:
            result = await self.llm_client.ainvoke_structured(
                schema,
                system_prompt=effective_system,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_retries=self.max_retries,
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

