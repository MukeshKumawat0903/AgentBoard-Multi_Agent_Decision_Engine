"""
Consensus scoring engine.

Computes agreement scores between agent positions to drive convergence.

V1 – ``ConsensusEngine`` (pure stdlib, no ML dependencies):
- compute_agreement_score              : mean confidence as group alignment proxy
- compute_confidence_weighted_score    : confidence-weighted pairwise Jaccard overlap
- detect_position_drift                : Jaccard-overlap delta between rounds

V2 – ``SemanticConsensusEngine`` (requires ``sentence-transformers``):
- compute_semantic_similarity          : mean pairwise cosine similarity of embeddings
- compute_agreement_score (override)   : hybrid = (1-w)*confidence + w*cosine_sim

SemanticConsensusEngine is feature-flagged via ``settings.SEMANTIC_CONSENSUS_ENABLED``
and gracefully degrades if ``sentence-transformers`` is not installed.
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


# ---------------------------------------------------------------------------
# Phase 4 – Semantic consensus engine (requires sentence-transformers + numpy)
# ---------------------------------------------------------------------------

try:
    import numpy as _np  # type: ignore[import-untyped]
    from sentence_transformers import SentenceTransformer as _ST  # type: ignore[import-untyped]
    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False


class SemanticConsensusEngine(ConsensusEngine):
    """
    Hybrid consensus engine: mean-confidence (V1) × cosine similarity (V2).

    Blending weight is passed per-call via ``semantic_weight`` so the
    caller (nodes.py) can read it from settings at runtime.

    Lazy model loading
    ------------------
    The sentence-transformer model (~80 MB) is downloaded and cached by
    the ``sentence_transformers`` library on first use, not at import time,
    so startup remains fast.

    Usage::

        engine = SemanticConsensusEngine()  # default model: all-MiniLM-L6-v2
        score = engine.compute_agreement_score(responses, semantic_weight=0.5)

    Raises
    ------
    ImportError
        If ``sentence-transformers`` or ``numpy`` are not installed.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        if not _SEMANTIC_AVAILABLE:
            raise ImportError(
                "sentence-transformers and numpy are required for SemanticConsensusEngine. "
                "Install them with: pip install sentence-transformers numpy"
            )
        self._model_name = model_name
        self._model: "_ST | None" = None  # lazy-loaded on first call

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_semantic_similarity(self, responses: list[AgentResponse]) -> float:
        """
        Mean pairwise cosine similarity over sentence-transformer embeddings.

        Returns:
            Float in [0, 1].  Returns 0.0 for fewer than 2 responses.
        """
        if len(responses) < 2:
            return 0.0

        model = self._load_model()
        positions = [r.position for r in responses]
        embeddings = model.encode(positions, convert_to_numpy=True)  # (n, d)

        # L2-normalise so dot product == cosine similarity
        norms = _np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalised = embeddings / _np.maximum(norms, 1e-8)
        sim_matrix: "_np.ndarray" = normalised @ normalised.T  # (n, n)

        n = len(responses)
        total, pairs = 0.0, 0
        for i in range(n):
            for j in range(i + 1, n):
                total += float(sim_matrix[i, j])
                pairs += 1

        return total / pairs if pairs else 0.0

    def compute_agreement_score(  # type: ignore[override]
        self,
        responses: list[AgentResponse],
        semantic_weight: float = 0.5,
    ) -> float:
        """
        Hybrid agreement score.

        ``score = (1 - w) × confidence_mean + w × cosine_similarity_mean``

        Falls back to the V1 confidence-only score on any exception so the
        debate can continue even if the embedding model misbehaves.

        Args:
            responses:       Agent responses for the current round.
            semantic_weight: Weight of the semantic component (0 → pure V1,
                             1 → pure cosine).  Defaults to 0.5.
        """
        base_score = super().compute_agreement_score(responses)
        if len(responses) < 2:
            return base_score

        try:
            semantic_score = self.compute_semantic_similarity(responses)
            hybrid = (1.0 - semantic_weight) * base_score + semantic_weight * semantic_score
            logger.debug(
                "semantic_agreement_score",
                extra={
                    "base": round(base_score, 4),
                    "semantic": round(semantic_score, 4),
                    "hybrid": round(hybrid, 4),
                    "weight": semantic_weight,
                },
            )
            return hybrid
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "semantic_scoring_failed_falling_back",
                extra={"error": str(exc)},
            )
            return base_score

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load_model(self) -> "_ST":
        # R5: reuse the module-level shared embedder to avoid loading weights twice
        from app.services.retriever import get_shared_embedder  # noqa: PLC0415
        return get_shared_embedder(self._model_name)  # type: ignore[return-value]
