"""
Simulation metrics must be able to say "stable": independently written
decisions share few exact words even when they agree, and recurring risks are
phrased differently from run to run.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.api_models import SimulateRequest, resolve_debate_config
from app.services.simulation import (
    _decision_consistency,
    _stability_rating,
    _stable_risk_flags,
)

# Two real decisions from separate debates on the same question; their word
# overlap (0.205) is the median for repeat runs in the dev database.
AGREE_A = ("Invest in the development of quantum computing while addressing technical, operational, "
           "financial, reputational, and regulatory challenges, and prioritizing ethical considerations "
           "to ensure fairness and mitigate potential biases.")
AGREE_B = ("Quantum computing has a promising future with potential applications in various fields, "
           "but its development and deployment must be carefully managed to address significant risks, "
           "challenges, and ethical concerns.")
UNRELATED = "Adopt a four-day work week pilot for the support team starting next quarter."


def test_consistent_runs_can_be_rated_high_and_unrelated_ones_low():
    from app.services.simulation import _jaccard

    assert _jaccard(AGREE_A, AGREE_B) == pytest.approx(0.205, abs=0.001)
    assert _stability_rating(_decision_consistency([AGREE_A, AGREE_B, AGREE_A])) == "High"
    assert _stability_rating(_decision_consistency([AGREE_A, UNRELATED])) == "Low"
    assert _decision_consistency(["Same text."] * 3) == pytest.approx(1.0)


def test_paraphrased_risk_flags_are_recognised_as_the_same_risk():
    runs = [
        ["Disruption of existing industries and job markets", "Regulatory uncertainty"],
        ["disruption of industries", "potential for quantum computers to break current encryption"],
        ["Industry disruption and job market changes", "Encryption could be broken"],
    ]
    stable = _stable_risk_flags(runs)
    assert stable == ["Disruption of existing industries and job markets"]


def test_generic_single_words_do_not_glue_different_risks_together():
    runs = [["Technical challenges"], ["Error correction challenges"], ["Financial challenges"]]
    assert _stable_risk_flags(runs) == []


def test_single_word_flags_still_match_exactly():
    assert _stable_risk_flags([["currency"], ["currency", "market"], ["Currency"]]) == ["currency"]


def test_mode_presets_decide_rounds_when_max_rounds_is_omitted():
    request = SimulateRequest(query="Should we adopt Kubernetes now?", mode="thorough")
    assert request.max_rounds is None
    assert resolve_debate_config(request.mode, request.max_rounds, None, None)[0] == 6
    quick = SimulateRequest(query="Should we adopt Kubernetes now?", mode="quick")
    assert resolve_debate_config(quick.mode, quick.max_rounds, None, None)[0] == 2


@pytest.mark.anyio
async def test_run_simulation_uses_the_mode_round_count():
    from app.schemas.final_decision import FinalDecision
    from app.schemas.state import DebateState
    from app.services.simulation import run_simulation

    decision = FinalDecision(thread_id="t", decision="Proceed.", rationale_summary="r", confidence_score=0.8,
                             agreement_score=0.8, total_rounds=1, termination_reason="consensus_reached")
    with patch("app.services.simulation.DebateGraph") as graph_cls:
        graph = MagicMock()
        graph.run = AsyncMock(return_value=(DebateState(user_query="Should we adopt?"), decision))
        graph.delete_checkpoints = AsyncMock()
        graph_cls.return_value = graph
        await run_simulation(query="Should we adopt Kubernetes now?", runs=2, max_rounds=None,
                             mode="thorough", llm_client=MagicMock(), settings=MagicMock())
    assert graph.run.call_args.kwargs["max_rounds"] == 6
