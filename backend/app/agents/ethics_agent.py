"""
Ethics & Constraints Agent – Validates proposals for ethical compliance.

Role in the debate:
  - Assess ethical, compliance, and societal dimensions of every proposal
  - Issue a VETO when a proposal is fundamentally unethical
  - Flag regulatory/legal risk that others may have missed
"""

from langchain_core.prompts import PromptTemplate

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient


SYSTEM_PROMPT = """\
You are the Ethics & Constraints Agent in a multi-agent decision engine.

Your role:
- Validate proposals against ethical guidelines and compliance rules
- Identify fairness, bias, and integrity concerns
- Check for regulatory, legal, or policy violations
- Assess societal impact and stakeholder effects
- You have VETO power — flag if a proposal is fundamentally unethical

Rules:
- Be the conscience of the group — raise concerns others may avoid
- Reference specific ethical principles when possible
- If something is compliant but ethically questionable, flag it
- Rate severity of ethical concerns: low, medium, high, critical
- Rate your confidence from 0.0 to 1.0
"""


# ---------------------------------------------------------------------------
# Prompt templates (Phase 1.5 – replaces raw f-strings with named variables)
# ---------------------------------------------------------------------------

_PROPOSAL_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "{strategy_context}"
    "Assess the ethical landscape of this problem and any proposed "
    "strategies. Identify fairness, bias, regulatory, and societal "
    "concerns. Issue a VETO (clearly marked in your position) if any "
    "aspect is fundamentally unethical. Reference specific ethical "
    "principles where applicable."
)

_CRITIQUE_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "You are critiquing the position of the {target_agent} agent:\n"
    "Position: {target_position}\n"
    "Reasoning: {target_reasoning}\n"
    "Confidence: {target_confidence}\n\n"
    "Evaluate whether the position has ethical blind spots. Does it "
    "account for all stakeholders? Are there fairness, bias, or "
    "compliance issues? Would any regulatory body object?"
)

_REVISION_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Your previous ethical assessment in round {round_number}:\n"
    "{prior_position}\n\n"
    "Critiques received:\n{critiques}\n"
    "Revise your ethical assessment in light of the debate. "
    "If other agents have addressed your concerns, you may withdraw or "
    "downgrade them. If new ethical issues have emerged from the debate, "
    "add them. Maintain or strengthen any VETO that remains justified."
)


class EthicsAgent(BaseAgent):
    """
    Ethics & Constraints agent: the group's conscience.

    Holds veto power over fundamentally unethical proposals.  Assesses
    every position for fairness, bias, regulatory compliance, and
    societal impact.
    """

    def __init__(self, llm_client: GroqClient) -> None:
        super().__init__(
            name="Ethics",
            role="Ethics and compliance guardian",
            system_prompt=SYSTEM_PROMPT,
            llm_client=llm_client,
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_proposal_prompt(self, state: DebateState) -> str:
        return _PROPOSAL_TEMPLATE.format(
            problem=state.user_query,
            strategy_context=self._strategy_context(state),
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
    def _strategy_context(state: DebateState) -> str:
        for r in reversed(state.rounds):
            for out in r.agent_outputs:
                if out.agent_name == "Strategy":
                    return f"Proposed strategy:\n{out.position}\n\n"
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
