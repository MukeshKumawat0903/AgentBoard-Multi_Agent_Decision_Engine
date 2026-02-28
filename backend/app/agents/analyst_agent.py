"""
Analyst Agent – Extracts facts, data points, and objective analysis.

Role in the debate:
  - Provide objective, evidence-based analysis of the problem
  - Identify key variables, cause-and-effect relationships, and data gaps
  - Explicitly state assumptions; never advocate for a strategy
"""

from app.agents.base_agent import BaseAgent
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient


SYSTEM_PROMPT = """\
You are the Analyst Agent in a multi-agent decision engine.

Your role:
- Extract key facts, data points, and variables from the problem
- Identify cause-and-effect relationships
- Provide objective analysis WITHOUT opinions or recommendations
- Quantify when possible; qualify when not

Rules:
- Do NOT propose a strategy — that's the Strategy Agent's job
- Do NOT assess risk — that's the Risk Agent's job
- Focus ONLY on what the data shows
- Always state your assumptions explicitly
- Rate your confidence from 0.0 to 1.0

You MUST respond with a single valid JSON object that matches this schema exactly:
{
  "position": "<your objective analysis>",
  "reasoning": "<step-by-step derivation>",
  "assumptions": ["<assumption 1>", "<assumption 2>"],
  "confidence_score": <float 0.0-1.0>
}
Output ONLY the JSON object. Do not include any prose before or after it.
"""


class AnalystAgent(BaseAgent):
    """
    Analyst agent: objective, data-driven analysis.

    Never advocates for a specific course of action — that is the Strategy
    Agent's responsibility.  Never assesses risk — that belongs to Risk.
    """

    def __init__(self, llm_client: GroqClient) -> None:
        super().__init__(
            name="Analyst",
            role="Objective data analyst",
            system_prompt=SYSTEM_PROMPT,
            llm_client=llm_client,
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_proposal_prompt(self, state: DebateState) -> str:
        prior = self._format_prior_rounds(state)
        return (
            f"Problem statement:\n{state.user_query}\n\n"
            f"{prior}"
            "Provide an objective analysis of the problem. Extract key facts, "
            "variables, and relationships. State all assumptions explicitly. "
            "Do NOT recommend a strategy."
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
            "Evaluate whether the claims are supported by evidence. "
            "Identify any factual inaccuracies, unsubstantiated claims, or "
            "missing data. Do NOT comment on strategy or risk — focus only on "
            "analytical rigour.\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "critique_points": ["<point 1>", "<point 2>"],\n'
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
            f"Your previous analysis in round {state.current_round}:\n"
            f"{self._last_position(state)}\n\n"
            f"Critiques received:\n{critique_text}\n"
            "Revise your analysis to address factual inaccuracies only. "
            "Do NOT change your analysis based on strategic preferences. "
            "If a critique is unfounded, explain why in your reasoning."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_prior_rounds(state: DebateState) -> str:
        if not state.rounds:
            return ""
        lines = ["Prior round summaries:"]
        for r in state.rounds:
            for out in r.agent_outputs:
                lines.append(f"  [{out.agent_name} R{r.round_number}] {out.position[:200]}")
        return "\n".join(lines) + "\n\n"

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
