"""
Scenario Simulation service for AgentBoard.

Runs N independent debates for the same query concurrently and
computes stability metrics across the runs.

Usage::

    from app.services.simulation import run_simulation

    result = await run_simulation(
        query="Should we adopt Kubernetes?",
        runs=3,
        max_rounds=4,
        mode="standard",
        llm_client=client,
        settings=settings,
    )
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.orchestrator.debate_graph import DebateGraph, require_decision

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.schemas.api_models import DebateMode
    from app.schemas.final_decision import FinalDecision
    from app.services.llm_client import LangChainProvider

logger = logging.getLogger("agentboard.simulation")


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------

class SimulationResult(BaseModel):
    """Aggregate result of N independent debate runs for the same query."""

    query: str
    runs: int = Field(description="Number of runs requested.")
    runs_completed: int = Field(description="Number of runs that completed successfully (≤ runs).")
    decisions: list[dict] = Field(description="Serialised FinalDecision objects for each run.")
    consistency_score: float = Field(
        ge=0.0, le=1.0,
        description=(
            "How alike the runs' decisions are: mean pairwise word overlap, rescaled so "
            "0 = as different as decisions to unrelated questions, 1 = the same decision reworded."
        ),
    )
    confidence_variance: float = Field(
        description="Standard deviation of agreement_score across runs.",
    )
    avg_agreement_score: float = Field(description="Mean agreement_score across all runs.")
    stable_risk_flags: list[str] = Field(
        description="Risk flags raised (in any wording) in at least 70 % of runs.",
    )
    stability_rating: str = Field(description="'High', 'Medium', or 'Low'.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _decision_consistency(texts: list[str]) -> float:
    """Mean pairwise agreement of decision texts on a calibrated 0–1 scale.

    Raw word overlap between two independently written decisions is low even
    when they agree (measured on stored debates: repeat runs of one question
    ~0.20, decisions to unrelated questions ~0.08), so each pair is rescaled with
    the same anchors the consensus gate uses before averaging.
    """
    if len(texts) <= 1:
        return 1.0
    from app.core.config import settings as app_settings
    from app.services.consensus import normalize_position_overlap

    scores = [
        normalize_position_overlap(
            _jaccard(texts[i], texts[j]),
            app_settings.POSITION_OVERLAP_FLOOR,
            app_settings.POSITION_OVERLAP_CEILING,
        )
        for i in range(len(texts))
        for j in range(i + 1, len(texts))
    ]
    return sum(scores) / len(scores)


_FLAG_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "by", "as", "is",
    "are", "be", "may", "can", "could", "will", "would", "its", "it", "this", "that", "from",
    "into", "over", "under", "about", "potential", "possible", "risk", "risks",
})


def _flag_tokens(flag: str) -> frozenset[str]:
    """Content words of a risk flag, lightly stemmed so wording variants match."""
    tokens = set()
    for raw in flag.lower().replace("-", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) < 3 or word in _FLAG_STOPWORDS:
            continue
        for suffix in ("ing", "ies", "es", "ed", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        tokens.add(word)
    return frozenset(tokens)


def _flags_match(a: frozenset[str], b: frozenset[str]) -> bool:
    """Same risk in different words: most of the shorter flag's words recur."""
    shared = a & b
    if not shared:
        return False
    shorter = min(len(a), len(b))
    return len(shared) / shorter >= 0.6 and (len(shared) >= 2 or shorter == 1)


def _stable_risk_flags(flag_lists: list[list[str]], min_share: float = 0.7) -> list[str]:
    """Flags raised — in any wording — by at least ``min_share`` of the runs.

    Each stable risk is reported once, in the wording where it first appeared.
    """
    needed = math.ceil(min_share * len(flag_lists))
    runs = [[(flag, _flag_tokens(flag)) for flag in flags] for flags in flag_lists]
    stable: list[tuple[str, frozenset[str]]] = []
    for flags in runs:
        for flag, tokens in flags:
            if not tokens or any(_flags_match(tokens, kept) for _, kept in stable):
                continue
            hits = sum(any(_flags_match(tokens, other) for _, other in run) for run in runs)
            if hits >= needed:
                stable.append((flag, tokens))
    return [flag for flag, _ in stable]


def _stability_rating(score: float) -> str:
    if score > 0.80:
        return "High"
    if score > 0.55:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

async def run_simulation(
    query: str,
    runs: int,
    max_rounds: int | None,
    mode: DebateMode,
    llm_client: LangChainProvider,
    settings: Settings,
    selected_agents: list[str] | None = None,
    knowledge_base=None,
    memory_store=None,
    use_knowledge_base: bool = False,
    enable_agent_memory: bool = False,
) -> SimulationResult:
    """
    Run ``runs`` independent debates and return aggregated stability metrics.

    The optional agent / knowledge-base / memory parameters let a simulation
    reproduce the exact configuration a single debate would use, so consistency
    is measured against the same setup the user is actually testing.
    """
    from app.schemas.api_models import resolve_debate_config
    from app.schemas.state import DebateState

    resolved_rounds, resolved_threshold, resolved_skip, resolved_min = resolve_debate_config(
        mode=mode,
        max_rounds=max_rounds,
        consensus_threshold=None,
        skip_critique_phase=None,
    )

    # Only build an explicit initial state when the run needs extra configuration
    # (agent subset, knowledge base, or memory); otherwise let the graph build it.
    needs_custom_state = bool(selected_agents) or use_knowledge_base or enable_agent_memory

    async def _single_run(_run_idx: int) -> FinalDecision | None:
        try:
            graph = DebateGraph(
                llm_client=llm_client,
                settings=settings,
                knowledge_base=knowledge_base,
                memory_store=memory_store,
                selected_agents=selected_agents,
            )
            if needs_custom_state:
                # Each run gets its own fresh state so concurrent runs never share it.
                run_state = DebateState(
                    user_query=query,
                    max_rounds=resolved_rounds,
                    min_rounds=resolved_min,
                    use_knowledge_base=use_knowledge_base,
                    enable_agent_memory=enable_agent_memory,
                    selected_agents=selected_agents,
                )
                _state, decision = await graph.run(
                    query,
                    initial_state=run_state,
                    consensus_threshold=resolved_threshold,
                    skip_critique_phase=resolved_skip,
                )
            else:
                _state, decision = await graph.run(
                    query,
                    max_rounds=resolved_rounds,
                    min_rounds=resolved_min,
                    consensus_threshold=resolved_threshold,
                    skip_critique_phase=resolved_skip,
                )
            decision = require_decision(decision)
            logger.info(
                "simulation_run_complete",
                extra={"run": _run_idx, "agreement_score": decision.agreement_score},
            )
            # Simulation runs are never resumed — don't let their checkpoints pile up.
            try:
                await graph.delete_checkpoints(_state.thread_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("simulation_checkpoint_cleanup_failed", extra={"error": str(exc)})
            return decision
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "simulation_run_failed",
                extra={"run": _run_idx, "error": str(exc)},
            )
            return None

    raw_results = await asyncio.gather(*[_single_run(i) for i in range(runs)])
    decisions: list[FinalDecision] = [r for r in raw_results if r is not None]

    if not decisions:
        return SimulationResult(
            query=query,
            runs=runs,
            runs_completed=0,
            decisions=[],
            consistency_score=0.0,
            confidence_variance=0.0,
            avg_agreement_score=0.0,
            stable_risk_flags=[],
            stability_rating="Low",
        )

    # Compute metrics
    decision_texts = [d.decision for d in decisions]
    consistency = _decision_consistency(decision_texts)

    agreement_scores = [d.agreement_score for d in decisions]
    avg_agreement = sum(agreement_scores) / len(agreement_scores)
    confidence_variance = statistics.stdev(agreement_scores) if len(agreement_scores) > 1 else 0.0

    # Stable risk flags: the same risk (in any wording) in >= 70 % of runs
    stable_flags = _stable_risk_flags([d.risk_flags for d in decisions])

    return SimulationResult(
        query=query,
        runs=runs,
        runs_completed=len(decisions),
        decisions=[d.model_dump() for d in decisions],
        consistency_score=round(consistency, 3),
        confidence_variance=round(confidence_variance, 3),
        avg_agreement_score=round(avg_agreement, 3),
        stable_risk_flags=stable_flags,
        stability_rating=_stability_rating(consistency),
    )
