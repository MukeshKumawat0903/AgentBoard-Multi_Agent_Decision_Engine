"""
Moderator Agent – Synthesizes all positions and drives convergence.

Role in the debate:
  - Remain strictly neutral — never takes sides
  - Compute an agreement score from agent positions each round
  - Decide whether to continue debating or produce the final decision
  - When converged: generate a structured FinalDecision
"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.services.llm_client import GroqClient
from app.utils.exceptions import LLMResponseError


# ---------------------------------------------------------------------------
# Moderator-specific schema
# ---------------------------------------------------------------------------

class ModeratorSynthesis(BaseModel):
    """
    Per-round synthesis produced by the Moderator.

    Drives the convergence check inside the DebateController.
    """

    summary: str = Field(description="Neutral summary of the current state of the debate.")
    agreement_areas: list[str] = Field(
        default_factory=list,
        description="Topics/claims all agents broadly agree on.",
    )
    disagreement_areas: list[str] = Field(
        default_factory=list,
        description="Topics/claims that remain in active dispute.",
    )
    agreement_score: float = Field(
        ge=0.0, le=1.0,
        description="0 = full disagreement, 1 = full consensus.",
    )
    should_continue: bool = Field(
        description="True = run another debate round; False = converged."
    )
    next_round_focus: str | None = Field(
        default=None,
        description="Key questions for the next round (only when should_continue=True).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "summary": "Agents broadly agree on market opportunity but disagree on timing.",
                "agreement_areas": ["Strong demand signal in SE Asia", "Singapore is low-risk entry"],
                "disagreement_areas": ["Q3 vs Q4 launch timing", "Budget allocation method"],
                "agreement_score": 0.62,
                "should_continue": True,
                "next_round_focus": "Resolve Q3 vs Q4 timing with supporting data.",
            }
        }
    )


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
You are the Moderator Agent in a multi-agent decision engine.

Your role:
- Synthesize all agent positions into a coherent summary
- Identify areas of agreement and disagreement
- Detect contradictions between agents
- Compute an agreement score (0.0 to 1.0) based on position alignment
- Determine if the debate has converged or needs more rounds

Rules:
- Be neutral — do NOT take sides
- Weight positions by each agent's confidence score
- Flag any unresolved disagreements
- If agreement_score >= 0.75 OR max rounds reached, set should_continue=false

You MUST respond with a single valid JSON object:
{
  "summary": "<neutral synthesis>",
  "agreement_areas": ["<area 1>", "<area 2>"],
  "disagreement_areas": ["<area 1>", "<area 2>"],
  "agreement_score": <float 0.0-1.0>,
  "should_continue": <true|false>,
  "next_round_focus": "<key question for next round, or null if not continuing>"
}
Output ONLY the JSON object.
"""

FINAL_DECISION_SYSTEM_PROMPT = """\
You are the Moderator Agent producing the FINAL DECISION of a multi-agent debate.

Your role:
- Synthesize all agent positions into a single, clear, actionable decision
- Provide a concise rationale summary
- List all identified risk flags
- List alternative options that were considered but not chosen
- Note any dissenting opinions among agents

You MUST respond with a single valid JSON object:
{
  "decision": "<clear, actionable decision statement>",
  "rationale_summary": "<concise explanation of why this decision was chosen>",
  "confidence_score": <float 0.0-1.0>,
  "agreement_score": <float 0.0-1.0>,
  "risk_flags": ["<risk 1>", "<risk 2>"],
  "alternatives": ["<alternative 1>", "<alternative 2>"],
  "dissenting_opinions": ["<dissent 1>"]
}
Output ONLY the JSON object.
"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ModeratorAgent(BaseAgent):
    """
    Moderator agent: synthesis, convergence, and final decision.

    Overrides ``run()`` to produce a ``ModeratorSynthesis`` instead of
    an ``AgentResponse`` (the standard agent interface does not apply
    cleanly to the moderator's neutral synthesis role).

    Extra public methods
    --------------------
    synthesize(state)  -> ModeratorSynthesis   (per-round agreement check)
    finalize(state)    -> FinalDecision         (end-of-debate output)
    """

    def __init__(self, llm_client: GroqClient) -> None:
        super().__init__(
            name="Moderator",
            role="Neutral synthesizer and convergence judge",
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            llm_client=llm_client,
        )

    # ------------------------------------------------------------------
    # Primary moderator operations
    # ------------------------------------------------------------------

    async def synthesize(self, state: DebateState) -> ModeratorSynthesis:
        """
        After all agents have proposed/critiqued/revised in a round,
        the Moderator synthesizes their positions and returns a
        ``ModeratorSynthesis`` that the DebateController uses for the
        convergence check.
        """
        user_prompt = self._build_synthesis_prompt(state)
        raw = await self._call_llm("synthesis", state.current_round, user_prompt)
        return self._parse_synthesis(raw, state.current_round)

    async def finalize(self, state: DebateState) -> FinalDecision:
        """
        Produce the ``FinalDecision`` at the end of the debate (either
        because consensus was reached or max rounds was hit).
        """
        user_prompt = self._build_finalize_prompt(state)
        # Temporarily swap system prompt for final-decision variant
        original_prompt = self.system_prompt
        self.system_prompt = FINAL_DECISION_SYSTEM_PROMPT
        try:
            raw = await self._call_llm("finalize", state.current_round, user_prompt)
        finally:
            self.system_prompt = original_prompt
        return self._parse_final_decision(raw, state)

    # ------------------------------------------------------------------
    # BaseAgent abstract methods – overridden but kept usable
    # ------------------------------------------------------------------

    async def run(self, state: DebateState) -> AgentResponse:  # type: ignore[override]
        """
        Drives a synthesis round.  Returns an ``AgentResponse`` that
        wraps the synthesis summary so it fits the standard agent
        interface while the richer ``ModeratorSynthesis`` is available
        via ``synthesize()``.
        """
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
        self, state: DebateState, target: AgentResponse
    ) -> str:
        return (
            f"As moderator, evaluate whether {target.agent_name}'s position "
            f"contributes constructively to debate round {state.current_round}:\n"
            f"Position: {target.position}\n"
        )

    def _build_revision_prompt(
        self, state: DebateState, critiques: list[CritiqueResponse]
    ) -> str:
        return self._build_synthesis_prompt(state)

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_synthesis_prompt(state: DebateState) -> str:
        agents_summary = ModeratorAgent._format_all_outputs(state)
        return (
            f"Problem statement:\n{state.user_query}\n\n"
            f"Debate round: {state.current_round} / {state.max_rounds}\n"
            f"Current agreement score: {state.agreement_score:.2f}\n\n"
            f"Agent positions this round:\n{agents_summary}\n"
            "Synthesize the above positions. Identify agreement and disagreement "
            "areas. Compute an agreement score (0.0–1.0). Set should_continue=false "
            "if agreement_score >= 0.75 OR this is the final round."
        )

    @staticmethod
    def _build_finalize_prompt(state: DebateState) -> str:
        all_rounds = ModeratorAgent._format_all_rounds(state)
        return (
            f"Problem statement:\n{state.user_query}\n\n"
            f"Total rounds completed: {state.current_round}\n"
            f"Final agreement score: {state.agreement_score:.2f}\n\n"
            f"Full debate history:\n{all_rounds}\n"
            "Produce the final decision synthesizing all agent input."
        )

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _parse_synthesis(self, raw: dict, round_number: int) -> ModeratorSynthesis:
        try:
            return ModeratorSynthesis.model_validate(raw)
        except Exception as exc:
            self.logger.error(
                "parse_synthesis_failed",
                extra={"round": round_number, "raw_keys": list(raw.keys()), "error": str(exc)},
            )
            raise LLMResponseError(
                f"[Moderator] ModeratorSynthesis parse failed: {exc}\nRaw keys: {list(raw.keys())}"
            ) from exc

    def _parse_final_decision(self, raw: dict, state: DebateState) -> FinalDecision:
        try:
            raw.setdefault("thread_id", state.thread_id)
            raw.setdefault("total_rounds", state.current_round)
            raw.setdefault(
                "termination_reason",
                "consensus_reached" if state.agreement_score >= 0.75 else "max_rounds_reached",
            )
            raw.setdefault("debate_trace", [r.model_dump() for r in state.rounds])
            return FinalDecision.model_validate(raw)
        except Exception as exc:
            self.logger.error(
                "parse_final_decision_failed",
                extra={"round": state.current_round, "raw_keys": list(raw.keys()), "error": str(exc)},
            )
            raise LLMResponseError(
                f"[Moderator] FinalDecision parse failed: {exc}\nRaw keys: {list(raw.keys())}"
            ) from exc

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_all_outputs(state: DebateState) -> str:
        if not state.rounds:
            return "(no agent outputs yet)"
        latest = state.rounds[-1]
        lines = []
        for out in latest.agent_outputs:
            lines.append(
                f"  [{out.agent_name}] (confidence={out.confidence_score:.2f}):\n"
                f"    {out.position[:400]}"
            )
        return "\n".join(lines) if lines else "(no outputs this round)"

    @staticmethod
    def _format_all_rounds(state: DebateState) -> str:
        lines = []
        for r in state.rounds:
            lines.append(f"--- Round {r.round_number} ---")
            for out in r.agent_outputs:
                lines.append(
                    f"  [{out.agent_name}] position: {out.position[:300]}"
                )
        return "\n".join(lines) if lines else "(no rounds completed)"
