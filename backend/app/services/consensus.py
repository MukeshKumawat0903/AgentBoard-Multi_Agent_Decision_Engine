"""
Consensus scoring engine.

Computes agreement scores between agent positions to drive convergence.

V1 implementation – pure stdlib, no embedding dependencies:
- compute_agreement_score  : mean confidence as a proxy for group alignment
- compute_confidence_weighted_score : confidence-weighted pairwise position overlap
- detect_position_drift    : Jaccard-overlap tracks how much each agent changed
                              between rounds (0 = identical, 1 = completely different)

V2 (future): replace Jaccard word-overlap with cosine similarity over LLM embeddings
for a semantically richer signal.
"""

from __future__ import annotations

import logging

from app.schemas.agent_response import AgentResponse

logger = logging.getLogger("agentboard.services.consensus")


def _word_overlap(a: str, b: str) -> float:
    """
    Jaccard similarity of the word sets of two strings.

    Returns a value in [0, 1] where 1 means identical word sets and
    0 means completely disjoint.  Case-insensitive.
    """
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class ConsensusEngine:
    """
    Measures agreement between agent positions to drive convergence decisions.

    All methods are pure functions of their arguments and carry no state,
    so a single instance can safely be reused across many debate sessions.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_agreement_score(self, responses: list[AgentResponse]) -> float:
        """
        V1 proxy: average confidence score across all agents.

        Rationale – higher confidence correlates with an agent that has
        settled on a position and is not expected to shift further, which
        loosely tracks inter-agent alignment.  V2 will overlay pairwise
        cosine similarity of embedded positions.

        Returns:
            Float in [0, 1].  Returns 0.0 for an empty list.
        """
        if not responses:
            logger.debug("compute_agreement_score called with empty list, returning 0.0")
            return 0.0
        score = sum(r.confidence_score for r in responses) / len(responses)
        logger.debug(
            "compute_agreement_score",
            extra={"n_agents": len(responses), "score": round(score, 4)},
        )
        return score

    def compute_confidence_weighted_score(self, responses: list[AgentResponse]) -> float:
        """
        Confidence-weighted inter-agent position overlap.

        For every ordered pair (i, j) with i ≠ j, compute the Jaccard word
        overlap of their positions and weight each pair by the *average*
        confidence of the two agents.  The final score is the sum of
        weighted overlaps divided by the sum of weights.

        Formula:
            score = Σ_{i≠j}(w_ij * sim_ij) / Σ_{i≠j}(w_ij)
            where w_ij = (conf_i + conf_j) / 2

        Returns:
            Float in [0, 1].  Returns 0.0 for fewer than 2 responses.
        """
        if len(responses) < 2:
            logger.debug(
                "compute_confidence_weighted_score: fewer than 2 responses, returning 0.0"
            )
            return 0.0

        weighted_sum = 0.0
        weight_total = 0.0

        for i, a in enumerate(responses):
            for j, b in enumerate(responses):
                if i >= j:
                    continue
                weight = (a.confidence_score + b.confidence_score) / 2.0
                similarity = _word_overlap(a.position, b.position)
                weighted_sum += weight * similarity
                weight_total += weight

        if weight_total == 0.0:
            return 0.0

        score = weighted_sum / weight_total
        logger.debug(
            "compute_confidence_weighted_score",
            extra={"n_agents": len(responses), "score": round(score, 4)},
        )
        return score

    def detect_position_drift(
        self,
        previous_responses: list[AgentResponse],
        current_responses: list[AgentResponse],
    ) -> float:
        """
        Measure how much agents changed their positions since the previous round.

        For each agent that appears in both lists the drift contribution is:
            drift_i = 1 - word_overlap(prev_position_i, curr_position_i)

        The overall drift score is the average across matched agents.

        Interpretation:
            0.0 – positions are identical (stagnation / stable consensus)
            1.0 – positions are completely new (maximum flux)

        Returns:
            Float in [0, 1].  Returns 0.0 if no agents are matched across
            the two rounds (e.g. first round has no previous round to compare).

        Usage:
            drift < 0.05 → agents have stopped moving → safe to terminate even
                           if the consensus threshold has not been reached.
        """
        if not previous_responses or not current_responses:
            logger.debug("detect_position_drift: one side is empty, returning 0.0")
            return 0.0

        prev_by_name: dict[str, str] = {r.agent_name: r.position for r in previous_responses}
        curr_by_name: dict[str, str] = {r.agent_name: r.position for r in current_responses}

        common_agents = set(prev_by_name) & set(curr_by_name)
        if not common_agents:
            return 0.0

        drift_sum = sum(
            1.0 - _word_overlap(prev_by_name[name], curr_by_name[name])
            for name in common_agents
        )
        score = drift_sum / len(common_agents)
        logger.debug(
            "detect_position_drift",
            extra={"common_agents": len(common_agents), "drift": round(score, 4)},
        )
        return score
