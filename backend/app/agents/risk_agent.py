"""
Risk Agent – Identifies risks, uncertainties, and failure modes.

Role in the debate:
  - Stress-test every proposed strategy and analysis
  - Surface hidden assumptions, edge cases, and tail risks
  - Categorize and rate every risk by probability and severity
"""

from langchain_core.prompts import PromptTemplate

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient


SYSTEM_PROMPT = """\
You are the Risk Agent in a multi-agent decision engine.

Your role:
- Identify risks, uncertainties, and potential failure modes
- Assess probability and impact of each risk
- Highlight what could go wrong with proposed strategies
- Identify hidden assumptions that others may have missed
- Flag edge cases and tail risks

Rules:
- Be adversarial but constructive — your job is to stress-test ideas
- Do NOT propose solutions — focus on what could fail
- Categorize risks: operational, financial, reputational, technical, regulatory
- Rate severity as: low, medium, high, critical
- Always state your confidence from 0.0 to 1.0
"""


# ---------------------------------------------------------------------------
# Prompt templates (Phase 1.5 – replaces raw f-strings with named variables)
# ---------------------------------------------------------------------------

_PROPOSAL_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "{analyst_context}"
    "Identify all significant risks in this problem. Categorize each "
    "risk (operational, financial, reputational, technical, regulatory) "
    "and rate its severity. Surface hidden assumptions and tail risks. "
    "Do NOT propose solutions."
)

_CRITIQUE_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "You are critiquing the position of the {target_agent} agent:\n"
    "Position: {target_position}\n"
    "Reasoning: {target_reasoning}\n"
    "Confidence: {target_confidence}\n\n"
    "Focus on risks the agent has overlooked or underestimated. "
    "Challenge any overly optimistic confidence scores. "
    "Identify hidden assumptions that could invalidate their position."
)

_REVISION_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Your previous risk assessment in round {round_number}:\n"
    "{prior_position}\n\n"
    "Critiques received:\n{critiques}\n"
    "Revise your risk assessment. Add any newly identified risks that "
    "emerged from other agents' positions. If a critique disputes one "
    "of your risks, either defend it with stronger evidence or withdraw it."
)


class RiskAgent(BaseAgent):
    """
    Risk agent: adversarial stress-tester.

    Never proposes solutions — focuses exclusively on identifying what
    could go wrong, categorised by type (operational/financial/
    reputational/technical/regulatory) and rated by severity.
    """

    def __init__(self, llm_client: GroqClient) -> None:
        super().__init__(
            name="Risk",
            role="Adversarial risk assessor",
            system_prompt=SYSTEM_PROMPT,
            llm_client=llm_client,
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_proposal_prompt(self, state: DebateState) -> str:
        return _PROPOSAL_TEMPLATE.format(
            problem=state.user_query,
            analyst_context=self._analyst_context(state),
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
    def _analyst_context(state: DebateState) -> str:
        for r in reversed(state.rounds):
            for out in r.agent_outputs:
                if out.agent_name == "Analyst":
                    return f"Analyst's findings:\n{out.position}\n\n"
        return ""

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
