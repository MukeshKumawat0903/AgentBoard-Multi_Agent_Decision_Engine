"""
Tests for the debate orchestrator / controller (Phase 6).

All LLM calls are mocked – no network traffic.

Coverage:
  DebateController construction
  initialize_state()
  _run_proposals()         – happy-path + graceful degradation
  _run_cross_examination() – parallel critiques, no self-critique
  _run_revisions()         – replaces original proposals in-place
  _run_convergence_check() – updates state agreement_score
  _should_terminate()      – consensus / max-rounds / high-confidence paths
  _finalize()              – sets state.status, populates debate_trace
  execute()                – full loop, consensus exit, max-rounds exit
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.moderator_agent import ModeratorSynthesis
from app.orchestrator.debate_controller import DebateController
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.utils.exceptions import LLMResponseError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_settings(
    *,
    max_rounds: int = 4,
    consensus_threshold: float = 0.75,
) -> MagicMock:
    s = MagicMock()
    s.MAX_DEBATE_ROUNDS = max_rounds
    s.CONSENSUS_THRESHOLD = consensus_threshold
    return s


def _mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.chat_json = AsyncMock()
    return llm


def _make_controller(max_rounds: int = 4, threshold: float = 0.75) -> DebateController:
    return DebateController(
        llm_client=_mock_llm(),
        settings=_mock_settings(max_rounds=max_rounds, consensus_threshold=threshold),
    )


def _agent_response(name: str, round_number: int = 1, confidence: float = 0.8) -> AgentResponse:
    return AgentResponse(
        agent_name=name,
        round_number=round_number,
        position=f"{name} recommends proceeding.",
        reasoning="Solid data.",
        confidence_score=confidence,
    )


def _critique_response(
    critic: str, target: str, round_number: int = 1
) -> CritiqueResponse:
    return CritiqueResponse(
        critic_agent=critic,
        target_agent=target,
        round_number=round_number,
        critique_points=["Needs more detail"],
        severity="low",
        confidence_score=0.7,
    )


def _synthesis(
    agreement_score: float = 0.8, should_continue: bool = False
) -> ModeratorSynthesis:
    return ModeratorSynthesis(
        summary="Broad agreement reached.",
        agreement_areas=["Market timing"],
        disagreement_areas=[],
        agreement_score=agreement_score,
        should_continue=should_continue,
        next_round_focus=None,
    )


def _final_decision(state: DebateState) -> FinalDecision:
    return FinalDecision(
        thread_id=state.thread_id,
        decision="Proceed with phased expansion.",
        rationale_summary="Consensus after debate.",
        confidence_score=0.85,
        agreement_score=state.agreement_score,
        total_rounds=max(1, state.current_round),
        termination_reason=state.termination_reason or "consensus_reached",
        debate_trace=[],  # will be replaced by _finalize()
    )


def _patch_all_agents(ctrl: DebateController, confidence: float = 0.8) -> None:
    """Replace every agent's run/critique/revise with AsyncMocks."""
    for name, agent in ctrl.agents.items():
        agent.run = AsyncMock(return_value=_agent_response(name, confidence=confidence))
        agent.critique = AsyncMock(
            side_effect=lambda state, target, _name=name: _critique_response(_name, target.agent_name)
        )
        agent.revise = AsyncMock(return_value=_agent_response(name, confidence=confidence))


def _patch_moderator(
    ctrl: DebateController,
    synthesis: ModeratorSynthesis,
    decision: FinalDecision | None = None,
) -> None:
    ctrl.moderator.synthesize = AsyncMock(return_value=synthesis)
    if decision is None:
        decision = _final_decision(ctrl.state or DebateState(user_query="x" * 10))
    ctrl.moderator.finalize = AsyncMock(return_value=decision)


async def _init(ctrl: DebateController, query: str = "Should we expand globally in Q3?") -> DebateState:
    return await ctrl.initialize_state(query)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestDebateControllerInit:

    def test_creates_four_debate_agents(self):
        ctrl = _make_controller()
        assert set(ctrl.agents.keys()) == {"Analyst", "Risk", "Strategy", "Ethics"}

    def test_moderator_is_separate(self):
        ctrl = _make_controller()
        assert ctrl.moderator is not None
        assert "Moderator" not in ctrl.agents

    def test_state_initially_none(self):
        ctrl = _make_controller()
        assert ctrl.state is None


# ---------------------------------------------------------------------------
# initialize_state()
# ---------------------------------------------------------------------------

class TestInitializeState:

    @pytest.mark.anyio
    async def test_returns_debate_state(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        assert isinstance(state, DebateState)

    @pytest.mark.anyio
    async def test_stores_query(self):
        ctrl = _make_controller()
        state = await _init(ctrl, "Should we enter the Asian market?")
        assert state.user_query == "Should we enter the Asian market?"

    @pytest.mark.anyio
    async def test_uses_settings_max_rounds_by_default(self):
        ctrl = _make_controller(max_rounds=3)
        state = await _init(ctrl)
        assert state.max_rounds == 3

    @pytest.mark.anyio
    async def test_accepts_custom_max_rounds(self):
        ctrl = _make_controller(max_rounds=4)
        state = await ctrl.initialize_state("Should we expand globally in Q3?", max_rounds=2)
        assert state.max_rounds == 2

    @pytest.mark.anyio
    async def test_assigns_thread_id(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        assert state.thread_id is not None and len(state.thread_id) > 0

    @pytest.mark.anyio
    async def test_sets_self_state(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        assert ctrl.state is state


# ---------------------------------------------------------------------------
# _run_proposals()
# ---------------------------------------------------------------------------

class TestRunProposals:

    @pytest.mark.anyio
    async def test_collects_responses_from_all_agents(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        state.rounds.append(DebateRound(round_number=1))
        _patch_all_agents(ctrl)

        outputs = await ctrl._run_proposals(state)

        assert len(outputs) == 4
        names = {o.agent_name for o in outputs}
        assert names == {"Analyst", "Risk", "Strategy", "Ethics"}

    @pytest.mark.anyio
    async def test_appends_to_round_agent_outputs(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        _patch_all_agents(ctrl)

        await ctrl._run_proposals(state)

        assert len(round_data.agent_outputs) == 4

    @pytest.mark.anyio
    async def test_graceful_degradation_on_agent_failure(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        state.rounds.append(DebateRound(round_number=1))
        _patch_all_agents(ctrl)

        # Make Analyst raise
        ctrl.agents["Analyst"].run = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        outputs = await ctrl._run_proposals(state)

        assert len(outputs) == 3  # 3 remaining agents succeed
        assert all(o.agent_name != "Analyst" for o in outputs)

    @pytest.mark.anyio
    async def test_all_agents_fail_returns_empty_list(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        state.rounds.append(DebateRound(round_number=1))

        for agent in ctrl.agents.values():
            agent.run = AsyncMock(side_effect=RuntimeError("fail"))

        outputs = await ctrl._run_proposals(state)
        assert outputs == []


# ---------------------------------------------------------------------------
# _run_cross_examination()
# ---------------------------------------------------------------------------

class TestRunCrossExamination:

    @pytest.mark.anyio
    async def test_produces_n_times_n_minus_1_critiques(self):
        """4 agents × 3 targets each = 12 critiques."""
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        _patch_all_agents(ctrl)

        # Populate proposals first
        round_data.agent_outputs = [_agent_response(n) for n in ctrl.agents]

        critiques = await ctrl._run_cross_examination(state)

        assert len(critiques) == 12

    @pytest.mark.anyio
    async def test_no_self_critiques(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        _patch_all_agents(ctrl)

        round_data.agent_outputs = [_agent_response(n) for n in ctrl.agents]
        critiques = await ctrl._run_cross_examination(state)

        for c in critiques:
            assert c.critic_agent != c.target_agent

    @pytest.mark.anyio
    async def test_appends_critiques_to_round_data(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        _patch_all_agents(ctrl)

        round_data.agent_outputs = [_agent_response(n) for n in ctrl.agents]
        await ctrl._run_cross_examination(state)

        assert len(round_data.critiques) == 12

    @pytest.mark.anyio
    async def test_failed_critique_skipped_gracefully(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        _patch_all_agents(ctrl)
        round_data.agent_outputs = [_agent_response(n) for n in ctrl.agents]

        # Analyst always raises on critique
        ctrl.agents["Analyst"].critique = AsyncMock(side_effect=RuntimeError("fail"))

        critiques = await ctrl._run_cross_examination(state)

        # 3 from Risk, Strategy, Ethics succeed; Analyst's 3 are skipped
        assert len(critiques) == 9


# ---------------------------------------------------------------------------
# _run_revisions()
# ---------------------------------------------------------------------------

class TestRunRevisions:

    @pytest.mark.anyio
    async def test_revisions_replace_original_proposals(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)

        # Populate proposals and targeted critiques
        for name in ctrl.agents:
            round_data.agent_outputs.append(_agent_response(name))
            round_data.critiques.append(_critique_response("Risk", name))

        # revise returns a response with updated position text
        for name, agent in ctrl.agents.items():
            revised = _agent_response(name, confidence=0.95)
            revised = revised.model_copy(update={"position": f"{name} revised"})
            agent.revise = AsyncMock(return_value=revised)

        await ctrl._run_revisions(state)

        for output in round_data.agent_outputs:
            assert "revised" in output.position

    @pytest.mark.anyio
    async def test_agents_without_critiques_are_not_revised(self):
        """If no critiques target an agent, revise() should not be called."""
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)

        for name in ctrl.agents:
            round_data.agent_outputs.append(_agent_response(name))
            agent = ctrl.agents[name]
            agent.revise = AsyncMock(return_value=_agent_response(name))

        # No critiques added to round_data → no revisions expected
        revised = await ctrl._run_revisions(state)
        assert revised == []
        for agent in ctrl.agents.values():
            agent.revise.assert_not_called()

    @pytest.mark.anyio
    async def test_updates_confidence_scores_in_state(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)

        for name in ctrl.agents:
            round_data.agent_outputs.append(_agent_response(name))
            round_data.critiques.append(_critique_response("Ethics", name))
            ctrl.agents[name].revise = AsyncMock(
                return_value=_agent_response(name, confidence=0.91)
            )

        await ctrl._run_revisions(state)

        for name in ctrl.agents:
            assert state.confidence_scores.get(name) == pytest.approx(0.91)


# ---------------------------------------------------------------------------
# _run_convergence_check()
# ---------------------------------------------------------------------------

class TestRunConvergenceCheck:

    @pytest.mark.anyio
    async def test_updates_state_agreement_score(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        for name in ctrl.agents:
            round_data.agent_outputs.append(_agent_response(name))

        ctrl.moderator.synthesize = AsyncMock(return_value=_synthesis(agreement_score=0.82))

        await ctrl._run_convergence_check(state)

        assert state.agreement_score == pytest.approx(0.82)

    @pytest.mark.anyio
    async def test_returns_moderator_synthesis(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        round_data = DebateRound(round_number=1)
        state.rounds.append(round_data)
        for name in ctrl.agents:
            round_data.agent_outputs.append(_agent_response(name))

        expected = _synthesis(agreement_score=0.6, should_continue=True)
        ctrl.moderator.synthesize = AsyncMock(return_value=expected)

        result = await ctrl._run_convergence_check(state)

        assert result is expected


# ---------------------------------------------------------------------------
# _should_terminate()
# ---------------------------------------------------------------------------

class TestShouldTerminate:

    def test_terminates_on_consensus(self):
        ctrl = _make_controller(threshold=0.75)
        state = DebateState(user_query="Should we expand globally in Q3?", current_round=1)
        synth = _synthesis(agreement_score=0.85, should_continue=False)

        result = ctrl._should_terminate(state, synth)

        assert result is True
        assert state.termination_reason == "consensus_reached"

    def test_terminates_at_max_rounds(self):
        ctrl = _make_controller(max_rounds=3, threshold=0.75)
        state = DebateState(user_query="Should we expand globally in Q3?", current_round=3, max_rounds=3)
        synth = _synthesis(agreement_score=0.50, should_continue=True)

        result = ctrl._should_terminate(state, synth)

        assert result is True
        assert state.termination_reason == "max_rounds_reached"

    def test_does_not_terminate_mid_debate(self):
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        state = DebateState(user_query="Should we expand globally in Q3?", current_round=2)
        synth = _synthesis(agreement_score=0.50, should_continue=True)

        result = ctrl._should_terminate(state, synth)

        assert result is False

    def test_terminates_on_high_confidence_when_moderator_says_stop(self):
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        state = DebateState(user_query="Should we expand globally in Q3?", current_round=2)
        state.confidence_scores = {
            "Analyst": 0.95, "Risk": 0.93, "Strategy": 0.91, "Ethics": 0.92
        }
        synth = _synthesis(agreement_score=0.70, should_continue=False)

        result = ctrl._should_terminate(state, synth)

        assert result is True
        assert state.termination_reason == "consensus_reached"

    def test_no_terminate_if_one_agent_low_confidence(self):
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        state = DebateState(user_query="Should we expand globally in Q3?", current_round=2)
        state.confidence_scores = {"Analyst": 0.95, "Risk": 0.60}
        synth = _synthesis(agreement_score=0.70, should_continue=False)

        result = ctrl._should_terminate(state, synth)

        assert result is False


# ---------------------------------------------------------------------------
# _finalize()
# ---------------------------------------------------------------------------

class TestFinalize:

    @pytest.mark.anyio
    async def test_sets_state_status_converged(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 2
        state.termination_reason = "consensus_reached"
        state.agreement_score = 0.88
        ctrl.moderator.finalize = AsyncMock(return_value=_final_decision(state))

        await ctrl._finalize(state)

        assert state.status == "converged"

    @pytest.mark.anyio
    async def test_sets_state_status_max_rounds(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 4
        state.termination_reason = "max_rounds_reached"
        state.agreement_score = 0.55
        ctrl.moderator.finalize = AsyncMock(return_value=_final_decision(state))

        await ctrl._finalize(state)

        assert state.status == "max_rounds_reached"

    @pytest.mark.anyio
    async def test_debate_trace_populated_from_state_rounds(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 2
        state.termination_reason = "consensus_reached"
        state.agreement_score = 0.8
        state.rounds = [DebateRound(round_number=1), DebateRound(round_number=2)]
        ctrl.moderator.finalize = AsyncMock(return_value=_final_decision(state))

        decision = await ctrl._finalize(state)

        assert len(decision.debate_trace) == 2

    @pytest.mark.anyio
    async def test_returns_final_decision(self):
        ctrl = _make_controller()
        state = await _init(ctrl)
        state.current_round = 1
        state.termination_reason = "consensus_reached"
        state.agreement_score = 0.9
        ctrl.moderator.finalize = AsyncMock(return_value=_final_decision(state))

        result = await ctrl._finalize(state)

        assert isinstance(result, FinalDecision)


# ---------------------------------------------------------------------------
# execute() – integration-level (all helpers mocked)
# ---------------------------------------------------------------------------

class TestExecute:

    @pytest.mark.anyio
    async def test_execute_raises_without_initialize(self):
        ctrl = _make_controller()
        with pytest.raises(RuntimeError, match="initialize_state"):
            await ctrl.execute()

    @pytest.mark.anyio
    async def test_execute_returns_final_decision(self):
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        state = await _init(ctrl)
        _patch_all_agents(ctrl)

        synth = _synthesis(agreement_score=0.85, should_continue=False)
        decision = _final_decision(state)
        _patch_moderator(ctrl, synth, decision)

        result = await ctrl.execute()

        assert isinstance(result, FinalDecision)

    @pytest.mark.anyio
    async def test_execute_terminates_after_one_round_at_consensus(self):
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        state = await _init(ctrl)
        _patch_all_agents(ctrl)

        synth = _synthesis(agreement_score=0.90, should_continue=False)
        _patch_moderator(ctrl, synth)

        await ctrl.execute()

        assert state.current_round == 1
        assert state.termination_reason == "consensus_reached"
        assert state.status == "converged"

    @pytest.mark.anyio
    async def test_execute_runs_all_rounds_if_no_consensus(self):
        ctrl = _make_controller(max_rounds=2, threshold=0.75)
        state = await _init(ctrl)
        _patch_all_agents(ctrl)

        # Never reach consensus
        synth = _synthesis(agreement_score=0.50, should_continue=True)
        _patch_moderator(ctrl, synth)

        await ctrl.execute()

        assert state.current_round == 2
        assert state.termination_reason == "max_rounds_reached"
        assert state.status == "max_rounds_reached"

    @pytest.mark.anyio
    async def test_execute_state_has_correct_number_of_rounds(self):
        ctrl = _make_controller(max_rounds=2, threshold=0.75)
        state = await _init(ctrl)
        _patch_all_agents(ctrl)

        synth = _synthesis(agreement_score=0.50, should_continue=True)
        _patch_moderator(ctrl, synth)

        await ctrl.execute()

        assert len(state.rounds) == 2

    @pytest.mark.anyio
    async def test_execute_state_status_in_progress_then_final(self):
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        status_during: list[str] = []

        original_run = ctrl.agents["Analyst"].run

        async def capture_status(s: DebateState) -> AgentResponse:
            status_during.append(s.status)
            return _agent_response("Analyst")

        ctrl.agents["Analyst"].run = capture_status
        state = await _init(ctrl)
        _patch_all_agents(ctrl)
        ctrl.agents["Analyst"].run = capture_status  # re-patch after _patch_all_agents

        synth = _synthesis(agreement_score=0.9, should_continue=False)
        _patch_moderator(ctrl, synth)

        await ctrl.execute()

        assert "in_progress" in status_during
        assert state.status == "converged"

    @pytest.mark.anyio
    async def test_execute_survives_one_failing_agent(self):
        """Debate completes even when one agent always fails on run()."""
        ctrl = _make_controller(max_rounds=4, threshold=0.75)
        state = await _init(ctrl)
        _patch_all_agents(ctrl)
        ctrl.agents["Ethics"].run = AsyncMock(side_effect=RuntimeError("LLM down"))

        synth = _synthesis(agreement_score=0.88, should_continue=False)
        _patch_moderator(ctrl, synth)

        result = await ctrl.execute()

        assert isinstance(result, FinalDecision)
        # Only 3 outputs per round (Ethics failed)
        assert len(state.rounds[0].agent_outputs) == 3

    @pytest.mark.anyio
    async def test_agreement_score_improves_across_rounds(self):
        """
        Verify that DebateState.agreement_score is updated (non-zero) after
        each convergence check and that the value recorded in state is the
        one returned by the moderator synthesis.
        """
        ctrl = _make_controller(max_rounds=3, threshold=0.95)  # high threshold forces all 3 rounds
        state = await _init(ctrl)
        _patch_all_agents(ctrl)

        scores = [0.50, 0.72, 0.88]
        call_count = 0

        async def _moderator_side_effect(*args, **kwargs):  # noqa: ARG001
            nonlocal call_count
            s = _synthesis(agreement_score=scores[call_count], should_continue=call_count < 2)
            call_count += 1
            return s

        ctrl.moderator.synthesize = _moderator_side_effect
        ctrl.moderator.finalize = AsyncMock(return_value=_final_decision(state))

        await ctrl.execute()

        # agreement_score in state should be the last synthesis value
        assert state.agreement_score >= scores[-1]
