"""
Moderator Agent - synthesizes positions and drives convergence.

Phase 1 migration: synthesize() and finalize() use structured output
schemas directly, eliminating manual JSON parsing and prompt-only JSON
enforcement.
"""

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient


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
        description="0 = full disagreement, 1 = full consensus.",
    )
    should_continue: bool = Field(
        description="True = run another round, False = converge and finalize.",
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
    "Compute an agreement score (0.0-1.0). Set should_continue=false if "
    "agreement_score >= 0.75 or this is the final round."
)

_FINALIZE_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Total rounds completed: {current_round}\n"
    "Final agreement score: {agreement_score}\n\n"
    "Full debate history:\n{all_rounds}\n"
    "Produce the final decision synthesizing all agent input."
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

    async def synthesize(self, state: DebateState) -> ModeratorSynthesis:
        user_prompt = self._build_synthesis_prompt(state)
        synthesis = await self.llm_client.ainvoke_structured(
            ModeratorSynthesis,
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        self.logger.info(
            "synthesis_complete",
            extra={
                "round": state.current_round,
                "agreement_score": synthesis.agreement_score,
                "should_continue": synthesis.should_continue,
            },
        )
        return synthesis

    async def finalize(self, state: DebateState) -> FinalDecision:
        user_prompt = self._build_finalize_prompt(state)
        llm_out = await self.llm_client.ainvoke_structured(
            FinalDecisionLLMOutput,
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
        )

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
