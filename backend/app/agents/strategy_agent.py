"""
Strategy Agent – Proposes concrete, actionable strategies.

Role in the debate:
  - Synthesize Analyst findings and Risk concerns into actionable plans
  - Always provide at least 2 alternative strategies alongside the primary
  - Be specific: avoid vague advice
"""

from langchain_core.prompts import PromptTemplate

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient

SYSTEM_PROMPT = """\
You are the Strategy Agent in a multi-agent decision engine.

Your role:
- Propose concrete, actionable strategies to address the problem
- Consider multiple options and recommend the best one
- Provide implementation steps where possible
- Balance risk and reward in your proposals

Rules:
- Ground strategies in the Analyst's findings when available
- Acknowledge risks identified by the Risk Agent
- Provide at least 2 alternatives alongside your main recommendation
- Be specific — avoid vague advice
- Rate your confidence from 0.0 to 1.0
"""


# ---------------------------------------------------------------------------
# Prompt templates (Phase 1.5 – replaces raw f-strings with named variables)
# ---------------------------------------------------------------------------

_PROPOSAL_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "{context}"
    "Propose a concrete, actionable strategy. Include implementation "
    "steps and at least 2 alternative options. Ground your strategy in "
    "the Analyst's findings and acknowledge any known risks."
)

_CRITIQUE_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "You are critiquing the position of the {target_agent} agent:\n"
    "Position: {target_position}\n"
    "Reasoning: {target_reasoning}\n"
    "Confidence: {target_confidence}\n\n"
    "Evaluate whether the position is actionable and strategically sound. "
    "Does it provide clear implementation steps? Are the alternatives "
    "sufficient? Is the recommended option the best choice given the "
    "risk-reward trade-off?"
)

_REVISION_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Your previous strategy in round {round_number}:\n"
    "{prior_position}\n\n"
    "Critiques received:\n{critiques}\n"
    "Revise your strategy to address the critiques. Incorporate risk "
    "mitigations flagged by the Risk Agent and ethical constraints from "
    "the Ethics Agent. If a critique is unfounded, defend your original "
    "position with stronger reasoning."
)


class StrategyAgent(BaseAgent):
    """
    Strategy agent: actionable plan proposer.

    Integrates Analyst findings and Risk concerns, then recommends the
    strongest course of action together with at least 2 alternatives.
    """

    def __init__(self, llm_client: GroqClient) -> None:
        super().__init__(
            name="Strategy",
            role="Actionable strategy proposer",
            system_prompt=SYSTEM_PROMPT,
            llm_client=llm_client,
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_proposal_prompt(self, state: DebateState) -> str:
        return _PROPOSAL_TEMPLATE.format(
            problem=state.user_query,
            context=self._build_context(state),
        )

    def _build_critique_prompt(
        self, state: DebateState, target: AgentResponse
    ) -> str:
        return _CRITIQUE_TEMPLATE.format(
            problem=state.user_query,
            target_agent=target.agent_name,
            target_position=target.position,
            target_reasoning=target.reasoning,
            target_confidence=target.confidence_score,
        )

    def _build_revision_prompt(
        self, state: DebateState, critiques: list[CritiqueResponse]
    ) -> str:
        return _REVISION_TEMPLATE.format(
            problem=state.user_query,
            round_number=state.current_round,
            prior_position=self._last_position(state),
            critiques=self._format_critiques(critiques),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(state: DebateState) -> str:
        lines = []
        for r in reversed(state.rounds):
            for out in r.agent_outputs:
                if out.agent_name == "Analyst" and not any("Analyst" in ln for ln in lines):
                    lines.append(f"Analyst findings:\n{out.position}")
                if out.agent_name == "Risk" and not any("Risk" in ln for ln in lines):
                    lines.append(f"Risk assessment:\n{out.position}")
        return ("\n\n".join(lines) + "\n\n") if lines else ""

    @staticmethod
    def _format_critiques(critiques: list[CritiqueResponse]) -> str:
        if not critiques:
            return "No critiques received."
        lines = []
        for c in critiques:
            points = "; ".join(c.critique_points)
            lines.append(f"  From {c.critic_agent} (severity={c.severity}): {points}")
            if c.suggested_revision:
                lines.append(f"    Suggestion: {c.suggested_revision}")
        return "\n".join(lines)

    def _last_position(self, state: DebateState) -> str:
        for r in reversed(state.rounds):
            for out in r.agent_outputs:
                if out.agent_name == self.name:
                    return out.position
        return "(no prior position)"
