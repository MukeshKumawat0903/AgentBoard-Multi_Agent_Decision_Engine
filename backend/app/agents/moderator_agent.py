"""
Moderator Agent - synthesizes positions and drives convergence.

Phase 1 migration: synthesize() and finalize() use structured output
schemas directly, eliminating manual JSON parsing and prompt-only JSON
enforcement.
"""

import asyncio

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision, StructuredDisagreement, VetoEntry
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient
from app.utils.exceptions import LLMRateLimitError

# Extra attempts for moderator calls rejected by the provider's rate limit, with
# the wait (seconds) before each. A rate-limited moderator call would otherwise
# end the whole debate after every agent call has already been paid for.
_RATE_LIMIT_BACKOFF_SECONDS: tuple[float, ...] = (10.0, 20.0)


class ModeratorSynthesis(BaseModel):
    """Per-round synthesis produced by the moderator."""

    summary: str = Field(description="Neutral summary of the current state of the debate.")
    agreement_areas: list[str] = Field(
        default_factory=list,
        description="Topics or claims all agents broadly agree on.",
    )
    disagreement_areas: list[str] = Field(
        default_factory=list,
        description="Topics or claims that remain in active dispute.",
    )
    agreement_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "The moderator's own estimate, 0 = full disagreement, 1 = full consensus. "
            "Logged only: the convergence gate uses the measured agreement."
        ),
    )
    should_continue: bool = Field(
        description=(
            "The moderator's recommendation (True = another round would help). "
            "The convergence gate makes the actual decision."
        ),
    )
    next_round_focus: str | None = Field(
        default=None,
        description="Key question for the next round when should_continue is true.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "summary": "Agents agree on market opportunity but disagree on timing.",
                "agreement_areas": ["Demand signal is strong", "Pilot market is low-risk"],
                "disagreement_areas": ["Q3 versus Q4 timing"],
                "agreement_score": 0.62,
                "should_continue": True,
                "next_round_focus": "Resolve timing with evidence.",
            }
        }
    )


class FinalDecisionLLMOutput(BaseModel):
    """LLM-generated core of the final decision."""

    decision: str = Field(min_length=1, description="Clear, actionable decision statement.")
    rationale_summary: str = Field(
        min_length=1,
        description="Concise explanation of why the decision was chosen.",
    )
    confidence_score: float = Field(ge=0.0, le=1.0)
    agreement_score: float = Field(ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    dissenting_opinions: list[str] = Field(default_factory=list)
    structured_disagreements: list[StructuredDisagreement] = Field(
        default_factory=list,
        description="Unresolved disagreements framed as the opposing agents' stances.",
    )


SYNTHESIS_SYSTEM_PROMPT = """\
You are the Moderator Agent in a multi-agent decision engine.

Your role:
- Synthesize all agent positions into a coherent summary
- Identify areas of agreement and disagreement
- Detect contradictions between agents
- Compute an agreement score (0.0 to 1.0) based on position alignment
- Determine if the debate has converged or needs more rounds

Rules:
- Be neutral and do not take sides
- Weight positions by each agent's confidence score
- Flag unresolved disagreements
- If agreement_score >= 0.75 or max rounds reached, set should_continue=false
"""

FINAL_DECISION_SYSTEM_PROMPT = """\
You are the Moderator Agent producing the final decision of a multi-agent debate.

Your role:
- Synthesize all agent positions into a single clear actionable decision
- Provide a concise rationale summary
- List identified risk flags
- List alternatives that were considered but not chosen
- Note dissenting opinions among agents
- For each unresolved disagreement, populate structured_disagreements: name the
  topic and the OPPOSING agents with their one-sentence stances (e.g. topic "Cost
  vs. worker harm" with Analyst arguing the savings justify it and Ethics arguing
  they do not). Frame these agent-vs-agent, not as one-sided critiques.
"""


# ---------------------------------------------------------------------------
# Prompt templates (Phase 1.5 – replaces raw f-strings with named variables)
# ---------------------------------------------------------------------------

_SYNTHESIS_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Debate round: {current_round} / {max_rounds}\n"
    "Current agreement score: {agreement_score}\n\n"
    "Agent positions this round:\n{agents_summary}\n"
    "Synthesize the positions. Identify agreement and disagreement areas. "
    "Estimate how far the agents agree (agreement_score, 0.0-1.0) and recommend "
    "whether another round would help (should_continue), with its key question "
    "(next_round_focus). Whether the debate stops is decided separately, from the "
    "agents' measured agreement."
)

_FINALIZE_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Total rounds completed: {current_round}\n"
    "Final agreement score: {agreement_score}\n\n"
    "Full debate history:\n{all_rounds}\n"
    "{human_direction}"
    "{standing_vetoes}"
    "Produce the final decision synthesizing all agent input."
)

# Appended to the finalize prompt while an Ethics-class veto still stands.
_STANDING_VETOES_TEMPLATE = (
    "\nStanding ethics vetoes — do not adopt the vetoed course as proposed; state "
    "how the decision addresses each one:\n{vetoes}\n\n"
)

# Appended to the finalize prompt when a human reviewer overrode the debate
# through the HITL panel; their direction takes precedence over the agents.
_HUMAN_DIRECTION_TEMPLATE = (
    "\nHuman reviewer override — the reviewer has given this direction, and the "
    "final decision MUST follow it. Use the debate to explain how to carry it out "
    "and which risks it carries:\n{feedback}\n\n"
)


class ModeratorAgent(BaseAgent):
    """Moderator agent: synthesis, convergence, and final decision."""

    def __init__(self, llm_client: GroqClient) -> None:
        super().__init__(
            name="Moderator",
            role="Neutral synthesizer and convergence judge",
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            llm_client=llm_client,
        )

    async def _invoke_with_rate_limit_backoff(
        self, schema, *, action: str, round_number: int, system_prompt: str, user_prompt: str
    ):
        """Call the LLM, waiting and retrying when the provider rate-limits us.

        Goes through ``_call_structured`` like the other agents, so the call is
        logged and uses this agent's configured temperature and retries.
        """
        waits = list(_RATE_LIMIT_BACKOFF_SECONDS)
        while True:
            try:
                return await self._call_structured(
                    schema, action, round_number, user_prompt, system_prompt=system_prompt
                )
            except LLMRateLimitError:
                if not waits:
                    raise
                delay = waits.pop(0)
                self.logger.warning(
                    "moderator_rate_limited_retrying",
                    extra={"schema": schema.__name__, "delay_s": delay},
                )
                await asyncio.sleep(delay)

    async def synthesize(self, state: DebateState) -> ModeratorSynthesis:
        user_prompt = self._build_synthesis_prompt(state)
        synthesis: ModeratorSynthesis = await self._invoke_with_rate_limit_backoff(
            ModeratorSynthesis,
            action="synthesize",
            round_number=state.current_round,
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        self.logger.info(
            "synthesis_complete",
            extra={
                "round": state.current_round,
                "moderator_agreement_estimate": synthesis.agreement_score,
                "moderator_recommends_continue": synthesis.should_continue,
            },
        )
        return synthesis

    async def finalize(self, state: DebateState) -> FinalDecision:
        user_prompt = self._build_finalize_prompt(state)
        llm_out = await self._invoke_with_rate_limit_backoff(
            FinalDecisionLLMOutput,
            action="finalize",
            round_number=state.current_round,
            system_prompt=FINAL_DECISION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        decision = FinalDecision(
            thread_id=state.thread_id,
            query=state.user_query,
            total_rounds=state.current_round,
            termination_reason=state.termination_reason or "max_rounds_reached",
            debate_trace=list(state.rounds),
            decision=llm_out.decision,
            rationale_summary=llm_out.rationale_summary,
            confidence_score=llm_out.confidence_score,
            agreement_score=llm_out.agreement_score,
            risk_flags=llm_out.risk_flags,
            alternatives=llm_out.alternatives,
            dissenting_opinions=llm_out.dissenting_opinions,
            structured_disagreements=llm_out.structured_disagreements,
            human_feedback=(state.human_feedback or "").strip() or None,
            vetoes=self._standing_vetoes(state),
        )
        self.logger.info(
            "finalize_complete",
            extra={
                "thread_id": state.thread_id,
                "total_rounds": state.current_round,
                "termination_reason": decision.termination_reason,
            },
        )
        return decision

    async def run(self, state: DebateState) -> AgentResponse:  # type: ignore[override]
        synthesis = await self.synthesize(state)
        return AgentResponse(
            agent_name=self.name,
            round_number=state.current_round,
            position=synthesis.summary,
            reasoning=(
                f"Agreement score: {synthesis.agreement_score:.2f}. "
                f"Continue: {synthesis.should_continue}. "
                f"Focus: {synthesis.next_round_focus or 'N/A'}"
            ),
            assumptions=[],
            confidence_score=synthesis.agreement_score,
        )

    def _build_proposal_prompt(self, state: DebateState) -> str:
        return self._build_synthesis_prompt(state)

    def _build_critique_prompt(
        self,
        state: DebateState,
        target: AgentResponse,
    ) -> str:
        return (
            f"As moderator, evaluate whether {target.agent_name}'s position "
            f"contributes constructively to debate round {state.current_round}:\n"
            f"Position: {target.position}\n"
        )

    def _build_revision_prompt(
        self,
        state: DebateState,
        critiques: list[CritiqueResponse],
    ) -> str:
        return self._build_synthesis_prompt(state)

    @staticmethod
    def _build_synthesis_prompt(state: DebateState) -> str:
        return _SYNTHESIS_TEMPLATE.format(
            problem=state.user_query,
            current_round=state.current_round,
            max_rounds=state.max_rounds,
            agreement_score=f"{state.agreement_score:.2f}",
            agents_summary=ModeratorAgent._format_all_outputs(state),
        )

    @staticmethod
    def _build_finalize_prompt(state: DebateState) -> str:
        return _FINALIZE_TEMPLATE.format(
            problem=state.user_query,
            current_round=state.current_round,
            agreement_score=f"{state.agreement_score:.2f}",
            all_rounds=ModeratorAgent._format_all_rounds(state),
            human_direction=(
                _HUMAN_DIRECTION_TEMPLATE.format(feedback=state.human_feedback.strip())
                if state.human_feedback and state.human_feedback.strip()
                else ""
            ),
            standing_vetoes=ModeratorAgent._format_vetoes(ModeratorAgent._standing_vetoes(state)),
        )

    @staticmethod
    def _standing_vetoes(state: DebateState) -> list[VetoEntry]:
        """Vetoes in the most recent round that has agent outputs."""
        for round_data in reversed(state.rounds):
            if round_data.agent_outputs:
                return [
                    VetoEntry(
                        agent_name=output.agent_name,
                        reason=(output.veto_reason or "").strip() or "No reason given.",
                        round_number=round_data.round_number,
                    )
                    for output in round_data.agent_outputs
                    if output.veto
                ]
        return []

    @staticmethod
    def _format_vetoes(vetoes: list[VetoEntry]) -> str:
        if not vetoes:
            return ""
        lines = "\n".join(f"- {v.agent_name}: {v.reason}" for v in vetoes)
        return _STANDING_VETOES_TEMPLATE.format(vetoes=lines)

    @staticmethod
    def _format_all_outputs(state: DebateState) -> str:
        if not state.rounds:
            return "(no agent outputs yet)"
        latest = state.rounds[-1]
        lines: list[str] = []
        for out in latest.agent_outputs:
            lines.append(
                f"  [{out.agent_name}] (confidence={out.confidence_score:.2f}):\n"
                f"    {out.position[:400]}"
            )
        return "\n".join(lines) if lines else "(no outputs this round)"

    @staticmethod
    def _format_all_rounds(state: DebateState) -> str:
        lines: list[str] = []
        for round_data in state.rounds:
            lines.append(f"--- Round {round_data.round_number} ---")
            for out in round_data.agent_outputs:
                lines.append(f"  [{out.agent_name}] position: {out.position[:300]}")
        return "\n".join(lines) if lines else "(no rounds completed)"
