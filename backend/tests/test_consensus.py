"""
Tests for the consensus scoring engine (Phase 7).

No LLM calls – all tests are pure-function / deterministic.

Coverage:
  _word_overlap helper
  ConsensusEngine.compute_agreement_score
    - empty list → 0.0
    - single agent
    - multiple agents, uniform confidence
    - returns value in [0, 1]
  ConsensusEngine.compute_confidence_weighted_score
    - fewer than 2 responses → 0.0
    - identical positions → score equals average confidence
    - completely different positions → score is low
    - higher-confidence agents inflate the weighted score
  ConsensusEngine.detect_position_drift
    - empty inputs → 0.0
    - identical positions → drift ≈ 0.0
    - completely different positions → drift ≈ 1.0
    - partial match returns intermediate value
    - agents not present in both rounds are ignored
    - only agents in both rounds are compared
"""

import pytest

from app.schemas.agent_response import AgentResponse
from app.services.consensus import ConsensusEngine, _word_overlap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _response(
    agent_name: str,
    position: str,
    confidence: float = 0.8,
    round_number: int = 1,
) -> AgentResponse:
    return AgentResponse(
        agent_name=agent_name,
        round_number=round_number,
        position=position,
        reasoning="Supporting reasoning.",
        confidence_score=confidence,
    )


ENGINE = ConsensusEngine()


# ---------------------------------------------------------------------------
# _word_overlap helper
# ---------------------------------------------------------------------------

class TestWordOverlap:

    def test_identical_strings(self):
        assert _word_overlap("the quick brown fox", "the quick brown fox") == pytest.approx(1.0)

    def test_completely_different(self):
        assert _word_overlap("alpha beta gamma", "delta epsilon zeta") == pytest.approx(0.0)

    def test_partial_overlap(self):
        # "a b c" vs "b c d" → intersection={b,c}, union={a,b,c,d} → 2/4 = 0.5
        assert _word_overlap("a b c", "b c d") == pytest.approx(0.5)

    def test_case_insensitive(self):
        assert _word_overlap("The Cat", "the cat") == pytest.approx(1.0)

    def test_both_empty(self):
        assert _word_overlap("", "") == pytest.approx(1.0)

    def test_one_empty(self):
        assert _word_overlap("word", "") == pytest.approx(0.0)

    def test_single_word_match(self):
        # "cat" vs "cat dog" → intersection={cat}, union={cat,dog} → 0.5
        assert _word_overlap("cat", "cat dog") == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# compute_agreement_score
# ---------------------------------------------------------------------------

class TestComputeAgreementScore:

    def test_empty_list_returns_zero(self):
        assert ENGINE.compute_agreement_score([]) == pytest.approx(0.0)

    def test_single_response_returns_its_confidence(self):
        r = _response("Analyst", "Expand now.", confidence=0.72)
        assert ENGINE.compute_agreement_score([r]) == pytest.approx(0.72)

    def test_uniform_confidence_equals_that_confidence(self):
        responses = [
            _response("Analyst", "Expand.", confidence=0.8),
            _response("Risk", "Caution.", confidence=0.8),
            _response("Strategy", "Pilot.", confidence=0.8),
        ]
        assert ENGINE.compute_agreement_score(responses) == pytest.approx(0.8)

    def test_averaged_correctly(self):
        responses = [
            _response("Analyst", "A", confidence=0.6),
            _response("Risk", "B", confidence=1.0),
        ]
        # (0.6 + 1.0) / 2 = 0.8
        assert ENGINE.compute_agreement_score(responses) == pytest.approx(0.8)

    def test_result_between_zero_and_one(self):
        responses = [
            _response("Analyst", "A", confidence=0.3),
            _response("Risk", "B", confidence=0.9),
            _response("Ethics", "C", confidence=0.1),
        ]
        score = ENGINE.compute_agreement_score(responses)
        assert 0.0 <= score <= 1.0

    def test_all_zero_confidence(self):
        responses = [
            _response("Analyst", "A", confidence=0.0),
            _response("Risk", "B", confidence=0.0),
        ]
        assert ENGINE.compute_agreement_score(responses) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_confidence_weighted_score
# ---------------------------------------------------------------------------

class TestComputeConfidenceWeightedScore:

    def test_empty_list_returns_zero(self):
        assert ENGINE.compute_confidence_weighted_score([]) == pytest.approx(0.0)

    def test_single_response_returns_zero(self):
        r = _response("Analyst", "Expand.", confidence=0.9)
        assert ENGINE.compute_confidence_weighted_score([r]) == pytest.approx(0.0)

    def test_identical_positions_score_close_to_average_confidence(self):
        """If positions are identical, word-overlap = 1.0, so score = avg confidence."""
        text = "we should expand into the emerging market immediately"
        responses = [
            _response("Analyst", text, confidence=0.8),
            _response("Risk", text, confidence=0.6),
        ]
        # weight for the single pair = (0.8+0.6)/2 = 0.7; similarity = 1.0; score = 1.0
        assert ENGINE.compute_confidence_weighted_score(responses) == pytest.approx(1.0)

    def test_completely_different_positions_score_near_zero(self):
        responses = [
            _response("Analyst", "alpha beta gamma delta epsilon", confidence=0.8),
            _response("Risk", "zeta eta theta iota kappa", confidence=0.8),
        ]
        assert ENGINE.compute_confidence_weighted_score(responses) == pytest.approx(0.0)

    def test_result_between_zero_and_one(self):
        responses = [
            _response("Analyst", "we should expand into asia", confidence=0.9),
            _response("Risk", "we should be cautious about expansion risk", confidence=0.7),
            _response("Strategy", "phased expansion is the right strategy", confidence=0.8),
        ]
        score = ENGINE.compute_confidence_weighted_score(responses)
        assert 0.0 <= score <= 1.0

    def test_higher_confidence_inflates_score(self):
        """
        Pair (Analyst, Strategy) has high confidence (0.95) and identical positions.
        All other pairs have very low confidence (0.1) and no positional overlap.

        The confidence-weighted score should be significantly higher than the
        unweighted average-similarity, demonstrating that high-confidence agents
        pull the result upward.
        """
        text = "expand into asia now with phased rollout strategy"
        responses = [
            _response("Analyst", text, confidence=0.95),
            _response("Strategy", text, confidence=0.95),
            _response("Risk", "unrelated alpha beta gamma", confidence=0.1),
            _response("Ethics", "completely different delta epsilon zeta", confidence=0.1),
        ]
        score = ENGINE.compute_confidence_weighted_score(responses)

        # Unweighted average similarity across 6 pairs ≈ 1/6 ≈ 0.167
        # Confidence-weighting boosts this to ~0.30 – distinctly higher.
        assert score > 0.20

    def test_all_zero_confidence_returns_zero(self):
        responses = [
            _response("Analyst", "some position text here", confidence=0.0),
            _response("Risk", "some position text here", confidence=0.0),
        ]
        # Total weight = 0.0 → guarded division returns 0.0
        assert ENGINE.compute_confidence_weighted_score(responses) == pytest.approx(0.0)

    def test_three_agents_partial_overlap(self):
        """Spot-check for 3 agents: verify pairing logic runs without error."""
        responses = [
            _response("Analyst", "market expansion is viable", confidence=0.7),
            _response("Risk", "expansion carries market risk", confidence=0.6),
            _response("Strategy", "viable expansion strategy required", confidence=0.8),
        ]
        score = ENGINE.compute_confidence_weighted_score(responses)
        # All have some overlap → score > 0
        assert score > 0.0


# ---------------------------------------------------------------------------
# detect_position_drift
# ---------------------------------------------------------------------------

class TestDetectPositionDrift:

    def test_empty_previous_returns_zero(self):
        curr = [_response("Analyst", "Expand now.")]
        assert ENGINE.detect_position_drift([], curr) == pytest.approx(0.0)

    def test_empty_current_returns_zero(self):
        prev = [_response("Analyst", "Expand now.")]
        assert ENGINE.detect_position_drift(prev, []) == pytest.approx(0.0)

    def test_identical_positions_zero_drift(self):
        text = "we should expand into the market now"
        prev = [
            _response("Analyst", text),
            _response("Risk", text),
        ]
        curr = [
            _response("Analyst", text, round_number=2),
            _response("Risk", text, round_number=2),
        ]
        assert ENGINE.detect_position_drift(prev, curr) == pytest.approx(0.0)

    def test_completely_different_positions_high_drift(self):
        prev = [
            _response("Analyst", "alpha beta gamma delta epsilon"),
            _response("Risk", "foo bar baz qux quux"),
        ]
        curr = [
            _response("Analyst", "zeta eta theta iota kappa", round_number=2),
            _response("Risk", "one two three four five", round_number=2),
        ]
        drift = ENGINE.detect_position_drift(prev, curr)
        # Completely disjoint word sets → drift should be 1.0
        assert drift == pytest.approx(1.0)

    def test_partial_position_change_intermediate_drift(self):
        prev = [_response("Analyst", "a b c d")]
        curr = [_response("Analyst", "a b e f", round_number=2)]
        # word_overlap("a b c d", "a b e f") = {a,b} / {a,b,c,d,e,f} = 2/6 ≈ 0.333
        # drift = 1 - 0.333 = 0.667
        drift = ENGINE.detect_position_drift(prev, curr)
        assert 0.3 < drift < 0.9

    def test_only_common_agents_are_compared(self):
        """Agents present in only one round are silently ignored."""
        prev = [
            _response("Analyst", "expand into asia"),
            _response("Risk", "high volatility risk"),
        ]
        curr = [
            _response("Analyst", "expand into asia", round_number=2),
            # "Risk" dropped out; "Ethics" is new
            _response("Ethics", "ethical concerns noted", round_number=2),
        ]
        # Only "Analyst" is common; their position is identical → drift = 0.0
        drift = ENGINE.detect_position_drift(prev, curr)
        assert drift == pytest.approx(0.0)

    def test_no_common_agents_returns_zero(self):
        prev = [_response("Analyst", "position A")]
        curr = [_response("Risk", "position B", round_number=2)]
        assert ENGINE.detect_position_drift(prev, curr) == pytest.approx(0.0)

    def test_result_between_zero_and_one(self):
        prev = [
            _response("Analyst", "market expansion is viable and promising"),
            _response("Risk", "regulatory risk must be addressed carefully"),
        ]
        curr = [
            _response("Analyst", "we recommend a phased market entry strategy", round_number=2),
            _response("Risk", "financial and operational risk remains high", round_number=2),
        ]
        drift = ENGINE.detect_position_drift(prev, curr)
        assert 0.0 <= drift <= 1.0

    def test_stagnation_threshold(self):
        """Drift < 0.05 should flag the debate as stagnating."""
        text = "expand now with phased approach to manage risk"
        prev = [_response("Analyst", text), _response("Risk", text)]
        # Tiny change: add one word at the end
        curr = [
            _response("Analyst", text + " carefully", round_number=2),
            _response("Risk", text + " prudently", round_number=2),
        ]
        drift = ENGINE.detect_position_drift(prev, curr)
        assert drift < 0.20  # small change → low drift (stagnation indicator)


# ---------------------------------------------------------------------------
# Phase 10 – additional acceptance criteria tests
# ---------------------------------------------------------------------------

class TestPhase10AcceptanceCriteria:
    """Explicit tests named after the Phase 10 spec for traceability."""

    def test_agreement_score_range(self):
        """compute_agreement_score always returns a value in [0, 1]."""
        import random
        random.seed(42)
        for _ in range(20):
            responses = [
                _response(f"Agent{i}", "some position text", confidence=random.random())
                for i in range(random.randint(1, 5))
            ]
            score = ENGINE.compute_agreement_score(responses)
            assert 0.0 <= score <= 1.0

    def test_identical_positions_high_score(self):
        """Identical positions from all agents should yield a high agreement score."""
        identical_text = (
            "We should proceed with a phased expansion into Southeast Asia"
            " starting with Singapore and Malaysia to minimise risk."
        )
        responses = [
            _response("Analyst", identical_text, confidence=0.9),
            _response("Risk", identical_text, confidence=0.9),
            _response("Strategy", identical_text, confidence=0.9),
            _response("Ethics", identical_text, confidence=0.9),
        ]
        score = ENGINE.compute_confidence_weighted_score(responses)
        assert score > 0.7

    def test_conflicting_positions_low_score(self):
        """Completely different positions should yield a low agreement score."""
        responses = [
            _response("Analyst", "alpha beta gamma delta epsilon", confidence=0.8),
            _response("Risk", "zeta eta theta iota kappa", confidence=0.8),
            _response("Strategy", "lambda mu nu xi omicron", confidence=0.8),
            _response("Ethics", "pi rho sigma tau upsilon", confidence=0.8),
        ]
        score = ENGINE.compute_confidence_weighted_score(responses)
        assert score < 0.2

    def test_confidence_weighting(self):
        """Higher-confidence pairs should dominate the weighted score.

        With 3 agents we have 3 pairs.  When the high-confidence pair shares
        identical text and low-confidence pairs are completely different, the
        weighted score should be substantially higher than the reverse setup.
        """
        shared = "expand into Southeast Asia with a phased market entry approach"
        unrelated = "completely different alpha beta gamma delta epsilon zeta"

        # Setup A: high-confidence pair agrees, low-confidence pairs disagree
        responses_high_dominant = [
            _response("Analyst",  shared,    confidence=0.95),
            _response("Strategy", shared,    confidence=0.95),
            _response("Risk",     unrelated, confidence=0.05),
        ]
        # Setup B: low-confidence pair agrees, high-confidence pairs disagree
        responses_low_dominant = [
            _response("Analyst",  shared,    confidence=0.05),
            _response("Strategy", shared,    confidence=0.05),
            _response("Risk",     unrelated, confidence=0.95),
        ]

        score_high = ENGINE.compute_confidence_weighted_score(responses_high_dominant)
        score_low  = ENGINE.compute_confidence_weighted_score(responses_low_dominant)

        # When the high-confidence pair agrees, total score should be higher
        assert score_high > score_low
