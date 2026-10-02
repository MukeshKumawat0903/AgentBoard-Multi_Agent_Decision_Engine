"""
Consensus scoring engine.

Computes the signals the hybrid consensus gate evaluates. The gate converges
only when all six hold (full write-up: docs/consensus_engine.md):

1. agreement >= the mode threshold (below);
2. at least ``min_rounds`` rounds debated;
3. at most ``MAX_DISSENTERS_FOR_CONSENSUS`` dissenters: voting agents whose
   stance differs from the majority stance (``select_dissenting_agents``);
4. at most ``MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS`` high/critical critiques
   still open *after revision*: each revision replies addressed / rebutted /
   unaddressed, and only unresolved ones count, a rebuttal not being enough
   for a critical one (``count_open_disagreements``);
5. confidence converged: positions stopped moving or agents are about equally
   sure (the "everyone is very confident" shortcut is off by default);
6. no standing Ethics-class veto.

Rule 1 — agreement score, chosen by ``AGREEMENT_METHOD`` or per debate:

- ``stance`` (default) – ``compute_stance_agreement``: each agent declares a
  structured verdict (support / oppose / conditional / abstain) toward the
  proposal on the table; agreement is the confidence-weighted vote share of
  the largest group. Abstainers do not vote.
- ``lexical`` – ``0.7 × mean confidence + 0.3 × rescaled word overlap``. Legacy,
  and the automatic fallback when fewer than two agents declared a stance.
- ``semantic`` – ``(1-w) × mean confidence + w × embedding cosine``.
  Experimental; needs ``SEMANTIC_CONSENSUS_ENABLED`` and sentence-transformers.

Why stance: text similarity (words or embeddings) measures *topic*, not
*verdict*. "Should expand" vs "should not expand" overlap almost completely,
and role-bound agents word their agreement differently. Every score is still
computed and reported each round; only the chosen one drives the gate.

V1 – ``ConsensusEngine`` (pure stdlib, no ML dependencies):
- compute_agreement_score              : mean confidence
- compute_confidence_weighted_score    : confidence-weighted pairwise Jaccard overlap
- detect_position_drift                : Jaccard-overlap delta between rounds

V2 – ``SemanticConsensusEngine`` (requires ``sentence-transformers``):
- compute_semantic_similarity          : mean pairwise cosine similarity of embeddings

With ``SEMANTIC_CONSENSUS_ENABLED`` the cosine score is a diagnostic (logged and
emitted) unless the ``semantic`` method is chosen; ``semantic_available()`` says
whether it can be. The engine degrades gracefully without sentence-transformers.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args

from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.state import AgreementMethod

if TYPE_CHECKING:
    from app.core.config import Settings

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
    ) -> float | None:
        """
        Measure how much agents changed their positions since the previous round.

        For each agent that appears in both lists the drift contribution is:
            drift_i = 1 - word_overlap(prev_position_i, curr_position_i)

        The overall drift score is the average across matched agents.

        Interpretation:
            0.0 – positions are identical (agents stopped moving)
            1.0 – positions are completely new (maximum flux)

        Returns:
            Float in [0, 1], or None when no agent appears in both rounds (round 1,
            or every agent from the previous round timed out). None means "not
            measurable"; it must never be read as 0.0, "no movement".

        Usage:
            drift < DRIFT_EARLY_STOP_THRESHOLD (0.05) is one of two ways to pass
            Rule 5 (Settled) of the consensus gate; the other is a tight
            confidence spread. It never ends a debate on its own: every other
            rule must still pass.
        """
        prev_by_name: dict[str, str] = {r.agent_name: r.position for r in previous_responses}
        curr_by_name: dict[str, str] = {r.agent_name: r.position for r in current_responses}

        common_agents = set(prev_by_name) & set(curr_by_name)
        if not common_agents:
            logger.debug("detect_position_drift: no agent in both rounds, not measurable")
            return None

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
# Stance-based agreement (Rule 1 of the consensus gate, default method)
#
# Text similarity — word overlap or embeddings — measures *topic*: role-bound
# agents write differently when they agree and alike when they don't ("should
# expand" vs "should not expand"). Each agent therefore declares its verdict as
# a structured ``stance`` and agreement is the vote share of the largest group.
# ---------------------------------------------------------------------------

AGREEMENT_METHODS: tuple[AgreementMethod, ...] = get_args(AgreementMethod)


def resolve_agreement_method(*candidates: object) -> AgreementMethod:
    """First candidate that names a known agreement method, else ``"stance"``.

    Called as ``resolve_agreement_method(per_debate_choice, settings.AGREEMENT_METHOD)``.
    """
    for candidate in candidates:
        if candidate in AGREEMENT_METHODS:
            return candidate  # type: ignore[return-value]
    return "stance"


MIN_STANCE_VOTERS = 2
# Deterministic tie-break between stance groups of equal weight and head count,
# so the gate and the minority report always pick the same majority.
_STANCE_TIE_ORDER: tuple[str, ...] = ("oppose", "conditional", "support")


def stance_weights(
    responses: list[AgentResponse],
) -> tuple[list[AgentResponse], dict[str, float]]:
    """Return (voters, summed confidence per stance).

    Voters are agents with a stance other than ``abstain``; agents with no stance
    (debates stored before the field existed) do not vote.
    """
    voters = [r for r in responses if r.stance and r.stance != "abstain"]
    weights: dict[str, float] = defaultdict(float)
    for r in voters:
        weights[r.stance] += r.confidence_score  # type: ignore[index]
    return voters, weights


def majority_stance(responses: list[AgentResponse]) -> str | None:
    """Stance group with the largest summed confidence.

    Ties go to the larger head count, then to ``_STANCE_TIE_ORDER``. Returns None
    when fewer than ``MIN_STANCE_VOTERS`` agents voted.
    """
    voters, weights = stance_weights(responses)
    if len(voters) < MIN_STANCE_VOTERS:
        return None
    heads = Counter(r.stance for r in voters)
    # Rounded so float noise (0.1 + 0.2 vs 0.3) can't break a genuine tie.
    return max(
        weights,
        key=lambda s: (round(weights[s], 9), heads[s], -_STANCE_TIE_ORDER.index(s)),
    )


def compute_stance_agreement(responses: list[AgentResponse]) -> float | None:
    """Confidence-weighted vote share of the largest stance group.

    Abstainers and agents with no stance are excluded. ``conditional`` is its own
    group: "yes, if X" is not counted as a plain "yes".
    Returns None when fewer than 2 agents voted, so the caller can fall back.
    """
    voters, weights = stance_weights(responses)
    if len(voters) < MIN_STANCE_VOTERS:
        return None
    total = sum(weights.values())
    return max(weights.values()) / total if total else 0.0


def stance_tally(responses: list[AgentResponse]) -> dict[str, int]:
    """Counts per stance, for logs/UI (e.g. {'support': 2, 'oppose': 1, 'abstain': 1}).

    Agents with no stance (debates stored before the field existed) are left out.
    """
    tally: dict[str, int] = {}
    for r in responses:
        if r.stance:
            tally[r.stance] = tally.get(r.stance, 0) + 1
    return tally


# ---------------------------------------------------------------------------
# Hybrid consensus gate — the signals and predicate that decide termination.
#
# The convergence gate no longer stops on mean confidence alone. It evaluates
# six signals, all of which must hold before a debate is declared converged.
# The dissent/disagreement helpers below are shared with finalize_node so the
# live gate and the final report agree on who dissented and what is still open.
# ---------------------------------------------------------------------------

# Severities that count as an unresolved disagreement for the convergence gate.
HIGH_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


def select_dissenting_agents(
    responses: list[AgentResponse], band: float
) -> list[AgentResponse]:
    """Voting agents whose stance differs from the majority stance.

    The majority is the stance group with the largest summed confidence (see
    ``majority_stance``); abstainers never dissent. A confident opponent is a
    dissenter, an unsure ally is not. When fewer than two agents voted (debates
    stored before stances existed) this falls back to the confidence gap: agents
    more than ``band`` below the group mean.

    Single definition of "dissenter", reused by both the convergence gate and
    the minority report in finalize_node so they never disagree.
    """
    majority = majority_stance(responses)
    if majority is None:
        return _confidence_gap_dissenters(responses, band)
    return [r for r in responses if r.stance not in (None, "abstain", majority)]


def _confidence_gap_dissenters(
    responses: list[AgentResponse], band: float
) -> list[AgentResponse]:
    """Agents whose confidence sits more than ``band`` below the group mean."""
    if not responses:
        return []
    mean_conf = sum(r.confidence_score for r in responses) / len(responses)
    return [r for r in responses if r.confidence_score < mean_conf - band]


def count_dissenting_agents(responses: list[AgentResponse], band: float) -> int:
    """Number of agents dissenting from the group, per ``select_dissenting_agents``."""
    return len(select_dissenting_agents(responses, band))


SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def build_reply_index(outputs: list[AgentResponse]) -> dict[str, dict[str, str]]:
    """``{target_agent: {critic_agent: status}}`` from this round's outputs.

    Revisions replace proposals in place, so these are the revised outputs; an
    agent whose revision failed still has its proposal, which carries no replies.
    """
    return {
        output.agent_name: {reply.critic_agent: reply.status for reply in output.critique_replies}
        for output in outputs
    }


def is_objection_open(severity: str, status: str) -> bool:
    """A critique stays open unless addressed; a rebuttal only settles a non-critical one."""
    return status == "unaddressed" or (status == "rebutted" and severity == "critical")


def select_open_disagreements(
    critiques: list[CritiqueResponse],
    replies: dict[str, dict[str, str]] | None = None,
    severities: frozenset[str] = HIGH_SEVERITIES,
) -> list[dict[str, str]]:
    """High/critical critic→target pairs not resolved by the target's revision.

    Each entry is ``{critic, target, severity, status}``. A critique with no reply
    (revision missing, failed or timed out) counts as ``unaddressed``. A pair is
    one objection however many critiques or bullet points it has; the most severe
    is reported. ``replies=None`` keeps the old behaviour: every high/critical
    critique counts as open.
    """
    open_pairs: dict[tuple[str, str], dict[str, str]] = {}
    for critique in critiques:
        if critique.severity not in severities:
            continue
        status = "unaddressed"
        if replies is not None:
            status = replies.get(critique.target_agent, {}).get(critique.critic_agent, "unaddressed")
        if not is_objection_open(critique.severity, status):
            continue
        pair = (critique.critic_agent, critique.target_agent)
        known = open_pairs.get(pair)
        if known is None or SEVERITY_RANK[critique.severity] < SEVERITY_RANK[known["severity"]]:
            open_pairs[pair] = {
                "critic": critique.critic_agent,
                "target": critique.target_agent,
                "severity": critique.severity,
                "status": status,
            }
    return list(open_pairs.values())


def count_open_disagreements(
    critiques: list[CritiqueResponse],
    replies: dict[str, dict[str, str]] | None = None,
    severities: frozenset[str] = HIGH_SEVERITIES,
) -> int:
    """Number of serious objections still open after revision.

    Counts distinct critic→target pairs from ``select_open_disagreements``, so a
    verbose critic can't inflate the count and a round that raises and fixes
    issues isn't punished. ``replies=None`` counts every high/critical critique.
    """
    return len(select_open_disagreements(critiques, replies, severities))


def normalize_position_overlap(raw_overlap: float, floor: float, ceiling: float) -> float:
    """Map raw word-overlap onto a 0–1 agreement scale.

    Agents write in deliberately different roles, so their raw Jaccard overlap
    stays low even when they agree. ``floor`` is the overlap of unrelated
    positions (scores 0) and ``ceiling`` the overlap of one agent restating the
    same stance (scores 1); values in between scale linearly. Without this the
    blended agreement score cannot reach the mode thresholds.
    """
    if ceiling <= floor:
        return max(0.0, min(1.0, raw_overlap))
    return max(0.0, min(1.0, (raw_overlap - floor) / (ceiling - floor)))


@dataclass(frozen=True)
class ConsensusSignals:
    """The signals the hybrid consensus gate evaluates."""

    position_agreement: float       # Rule 1 agreement score [0,1] (stance / lexical / semantic)
    rounds_completed: int           # ds.current_round
    dissenting_agents: int          # agents voting against the majority stance
    open_disagreements: int         # high/critical critiques still open after revision
    confidence_converged: bool      # agents stopped moving or are about equally sure
    active_vetoes: int = 0          # Ethics-class vetoes standing this round


def is_consensus_reached(
    signals: ConsensusSignals,
    *,
    threshold: float,
    min_rounds: int,
    max_dissent: int,
    max_open_disagreements: int,
) -> bool:
    """Hybrid consensus predicate — every criterion must hold.

    Replaces the single mean-confidence gate: a debate only converges when the
    agents genuinely agree, have debated a minimum number of rounds, overrule
    at most a few agents, leave few serious critiques open after revision,
    have either stopped moving or are about equally sure, and no ethics veto
    stands.
    """
    return (
        signals.active_vetoes == 0
        and signals.position_agreement >= threshold
        and signals.rounds_completed >= min_rounds
        and signals.dissenting_agents <= max_dissent
        and signals.open_disagreements <= max_open_disagreements
        and signals.confidence_converged
    )


# ---------------------------------------------------------------------------
# Phase 4 – Semantic consensus engine (requires sentence-transformers + numpy)
# ---------------------------------------------------------------------------

try:
    import numpy as _np  # type: ignore[import-untyped]
    from sentence_transformers import SentenceTransformer as _ST  # type: ignore[import-untyped]
    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False


def semantic_libraries_installed() -> bool:
    """True when ``sentence-transformers`` and ``numpy`` could be imported."""
    return _SEMANTIC_AVAILABLE


def semantic_available(settings: Settings | None = None) -> bool:
    """True when the semantic score can be computed on this server.

    Needs both the ``SEMANTIC_CONSENSUS_ENABLED`` flag and the embedding
    libraries. The "semantic" agreement method is only offered when this holds.
    """
    if settings is None:
        from app.core.config import settings as app_settings  # noqa: PLC0415
        settings = app_settings
    return bool(settings.SEMANTIC_CONSENSUS_ENABLED) and semantic_libraries_installed()


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
        if not semantic_libraries_installed():
            raise ImportError(
                "sentence-transformers and numpy are required for SemanticConsensusEngine. "
                "Install them with: pip install sentence-transformers numpy"
            )
        self._model_name = model_name
        self._model: _ST | None = None  # lazy-loaded on first call

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_semantic_similarity(self, responses: list[AgentResponse]) -> float:
        """
        Mean pairwise cosine similarity over sentence-transformer embeddings.

        Synchronous and CPU-bound: async callers must run it in a worker thread
        (``asyncio.to_thread``) so it never blocks the event loop.

        Returns:
            Float in [0, 1].  Returns 0.0 for fewer than 2 responses.
        """
        if len(responses) < 2:
            return 0.0

        model = self._load_model()
        # all-MiniLM-L6-v2 truncates its input at 256 word-pieces, so only the
        # opening of a long position is embedded. Embeddings also capture topic
        # more than verdict ("expand" vs "do not expand" score close), which is
        # why this score is a diagnostic by default and not the agreement metric.
        positions = [r.position for r in responses]
        embeddings = model.encode(positions, convert_to_numpy=True)  # (n, d)

        # L2-normalise so dot product == cosine similarity
        norms = _np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalised = embeddings / _np.maximum(norms, 1e-8)
        sim_matrix: _np.ndarray = normalised @ normalised.T  # (n, n)

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

    def _load_model(self) -> _ST:
        # R5: reuse the module-level shared embedder to avoid loading weights twice
        from app.services.retriever import get_shared_embedder  # noqa: PLC0415
        model: _ST = get_shared_embedder(self._model_name)
        return model
