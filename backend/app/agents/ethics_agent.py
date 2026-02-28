"""
Ethics & Constraints Agent – Validates proposals for ethical compliance.

Role in the debate:
  - Assess ethical, compliance, and societal dimensions of every proposal
  - Issue a VETO when a proposal is fundamentally unethical
  - Flag regulatory/legal risk that others may have missed
"""

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

You MUST respond with a single valid JSON object that matches this schema exactly:
{
  "position": "<your ethical assessment, including VETO if applicable>",
  "reasoning": "<step-by-step ethical reasoning>",
  "assumptions": ["<assumption 1>", "<assumption 2>"],
  "confidence_score": <float 0.0-1.0>
}
Output ONLY the JSON object. Do not include any prose before or after it.
"""


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
        strategy_context = self._strategy_context(state)
        return (
            f"Problem statement:\n{state.user_query}\n\n"
            f"{strategy_context}"
            "Assess the ethical landscape of this problem and any proposed "
            "strategies. Identify fairness, bias, regulatory, and societal "
            "concerns. Issue a VETO (clearly marked in your position) if any "
            "aspect is fundamentally unethical. Reference specific ethical "
            "principles where applicable."
        )

    def _build_critique_prompt(
        self, state: DebateState, target: AgentResponse
    ) -> str:
        return (
            f"Problem statement:\n{state.user_query}\n\n"
            f"You are critiquing the position of the {target.agent_name} agent:\n"
            f"Position: {target.position}\n"
            f"Reasoning: {target.reasoning}\n"
            f"Confidence: {target.confidence_score}\n\n"
            "Evaluate whether the position has ethical blind spots. Does it "
            "account for all stakeholders? Are there fairness, bias, or "
            "compliance issues? Would any regulatory body object?\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "critique_points": ["<ethical issue 1>", "<ethical issue 2>"],\n'
            '  "severity": "<low|medium|high|critical>",\n'
            '  "suggested_revision": "<optional concrete suggestion or null>",\n'
            '  "confidence_score": <float 0.0-1.0>\n'
            "}"
        )

    def _build_revision_prompt(
        self, state: DebateState, critiques: list[CritiqueResponse]
    ) -> str:
        critique_text = self._format_critiques(critiques)
        return (
            f"Problem statement:\n{state.user_query}\n\n"
            f"Your previous ethical assessment in round {state.current_round}:\n"
            f"{self._last_position(state)}\n\n"
            f"Critiques received:\n{critique_text}\n"
            "Revise your ethical assessment in light of the debate. "
            "If other agents have addressed your concerns, you may withdraw or "
            "downgrade them. If new ethical issues have emerged from the debate, "
            "add them. Maintain or strengthen any VETO that remains justified."
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
