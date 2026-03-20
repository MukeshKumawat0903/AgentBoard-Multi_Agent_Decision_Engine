"""
Analyst Agent – Extracts facts, data points, and objective analysis.

Role in the debate:
  - Provide objective, evidence-based analysis of the problem
  - Identify key variables, cause-and-effect relationships, and data gaps
  - Explicitly state assumptions; never advocate for a strategy
"""

from langchain_core.prompts import PromptTemplate

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
"""


# ---------------------------------------------------------------------------
# Prompt templates (Phase 1.5 – replaces raw f-strings with named variables)
# ---------------------------------------------------------------------------

_PROPOSAL_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "{prior_rounds}"
    "Provide an objective analysis of the problem. Extract key facts, "
    "variables, and relationships. State all assumptions explicitly. "
    "Do NOT recommend a strategy."
)

_CRITIQUE_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "You are critiquing the position of the {target_agent} agent:\n"
    "Position: {target_position}\n"
    "Reasoning: {target_reasoning}\n"
    "Confidence: {target_confidence}\n\n"
    "Evaluate whether the claims are supported by evidence. "
    "Identify any factual inaccuracies, unsubstantiated claims, or "
    "missing data. Do NOT comment on strategy or risk — focus only on "
    "analytical rigour."
)

_REVISION_TEMPLATE = PromptTemplate.from_template(
    "Problem statement:\n{problem}\n\n"
    "Your previous analysis in round {round_number}:\n"
    "{prior_position}\n\n"
    "Critiques received:\n{critiques}\n"
    "Revise your analysis to address factual inaccuracies only. "
    "Do NOT change your analysis based on strategic preferences. "
    "If a critique is unfounded, explain why in your reasoning."
)


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
        return _PROPOSAL_TEMPLATE.format(
            problem=state.user_query,
            prior_rounds=self._format_prior_rounds(state),
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
