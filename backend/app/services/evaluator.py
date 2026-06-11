"""
Decision Quality Evaluator for AgentBoard.

Uses an LLM-as-judge pattern to score a FinalDecision against four
dimensions:  completeness, consistency, actionability, risk_awareness.

Results are cached in the ``decisions.evaluation_json`` column to avoid
re-evaluating the same decision.

Usage::

    from app.services.evaluator import evaluate_decision

    result = await evaluate_decision(decision, llm_client=client)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.schemas.final_decision import FinalDecision
    from app.services.llm_client import LangChainProvider

logger = logging.getLogger("agentboard.evaluator")


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class EvaluationScores(BaseModel):
    """LLM-generated quality scores for a decision."""

    completeness: float = Field(
        ge=0.0, le=1.0,
        description="Does the decision address all aspects of the query? (0–1)",
    )
    consistency: float = Field(
        ge=0.0, le=1.0,
        description="Are the decision and reasoning internally consistent without contradictions? (0–1)",
    )
    actionability: float = Field(
        ge=0.0, le=1.0,
        description="Does the decision contain specific, implementable next steps? (0–1)",
    )
    risk_awareness: float = Field(
        ge=0.0, le=1.0,
        description="Are relevant risks identified and adequately addressed? (0–1)",
    )
    reasoning: str = Field(
        description="One paragraph explaining the scores with specific evidence from the decision.",
    )


class EvaluationResult(BaseModel):
    """Full evaluation result including computed overall score."""

    thread_id: str
    completeness: float
    consistency: float
    actionability: float
    risk_awareness: float
    overall: float
    reasoning: str
    evaluated_at: str


# ---------------------------------------------------------------------------
# Evaluator function
# ---------------------------------------------------------------------------

_EVAL_SYSTEM_PROMPT = """\
You are an objective decision quality evaluator.
You will receive a query and the final decision produced by a multi-agent debate system.
Your task is to score the decision on four dimensions, each from 0.0 to 1.0:

1. completeness   – Does the decision address ALL aspects of the original query?
2. consistency    – Is the decision internally coherent with NO factual contradictions?
3. actionability  – Does it contain concrete, implementable next steps (not vague platitudes)?
4. risk_awareness – Are the relevant risks clearly identified and addressed?

Score 0.9–1.0 = excellent, 0.7–0.8 = good, 0.5–0.6 = adequate, below 0.5 = poor.
Be calibrated and critical.  Provide brief reasoning with evidence from the decision text.
"""


async def evaluate_decision(
    decision: FinalDecision,
    llm_client: LangChainProvider,
) -> EvaluationResult:
    """
    Score a FinalDecision on four quality dimensions using an LLM judge.

    Returns an EvaluationResult with individual and overall scores.
    """
    user_prompt = (
        f"## Original Query\n{decision.query or 'N/A'}\n\n"
        f"## Final Decision\n{decision.decision}\n\n"
        f"## Rationale Summary\n{decision.rationale_summary}\n\n"
        f"## Risk Flags\n{chr(10).join(f'- {r}' for r in decision.risk_flags) or 'None'}\n\n"
        f"## Alternatives Considered\n{chr(10).join(f'- {a}' for a in decision.alternatives) or 'None'}\n\n"
        "Please score the decision quality on the four dimensions."
    )

    try:
        scores = await llm_client.ainvoke_structured(
            EvaluationScores,
            system_prompt=_EVAL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception as exc:
        logger.error(
            "evaluation_failed",
            extra={"thread_id": decision.thread_id, "error": str(exc)},
        )
        raise

    overall = round(
        (scores.completeness + scores.consistency + scores.actionability + scores.risk_awareness) / 4,
        3,
    )
    return EvaluationResult(
        thread_id=decision.thread_id,
        completeness=round(scores.completeness, 3),
        consistency=round(scores.consistency, 3),
        actionability=round(scores.actionability, 3),
        risk_awareness=round(scores.risk_awareness, 3),
        overall=overall,
        reasoning=scores.reasoning,
        evaluated_at=datetime.now(UTC).isoformat(),
    )
