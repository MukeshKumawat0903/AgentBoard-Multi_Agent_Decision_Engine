"""
A HITL "override" must actually steer the final decision: the reviewer's
feedback has to reach the moderator's finalize prompt and be recorded on the
decision, and an override without feedback is rejected.
"""

import pytest
from pydantic import ValidationError

from app.agents.base_agent import AgentLLMOutput, CritiqueLLMOutput
from app.agents.moderator_agent import (
    FinalDecisionLLMOutput,
    ModeratorAgent,
    ModeratorSynthesis,
)
from app.core.config import settings
from app.orchestrator.debate_graph import DebateGraph
from app.schemas.api_models import ApproveRequest
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.exporter import render_html, render_markdown

FEEDBACK = "Go with vendor B and keep the rollout to two regions."


class _RecordingLLM:
    """Deterministic stand-in for the LLM that remembers every prompt it saw."""

    provider = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    async def ainvoke_structured(self, schema, system_prompt, user_prompt, **_kwargs):
        self.prompts.append((schema.__name__, user_prompt))
        if schema is AgentLLMOutput:
            return AgentLLMOutput(position="Run a careful pilot first.", reasoning="r", confidence_score=0.9, stance="support")
        if schema is CritiqueLLMOutput:
            return CritiqueLLMOutput(critique_points=["minor"], severity="low", confidence_score=0.5)
        if schema is ModeratorSynthesis:
            return ModeratorSynthesis(summary="s", agreement_score=0.9, should_continue=False)
        if schema is FinalDecisionLLMOutput:
            return FinalDecisionLLMOutput(
                decision="Proceed", rationale_summary="why", confidence_score=0.8, agreement_score=0.8
            )
        raise AssertionError(f"unexpected schema {schema}")

    def finalize_prompts(self) -> list[str]:
        return [p for name, p in self.prompts if name == "FinalDecisionLLMOutput"]


def _state(**overrides) -> DebateState:
    return DebateState(user_query="Which vendor should we pick for the rollout?", **overrides)


class TestFinalizePrompt:
    def test_includes_reviewer_direction_when_present(self):
        prompt = ModeratorAgent._build_finalize_prompt(_state(human_feedback=FEEDBACK))
        assert FEEDBACK in prompt
        assert "MUST follow" in prompt

    def test_has_no_reviewer_section_without_feedback(self):
        for feedback in (None, "", "   "):
            prompt = ModeratorAgent._build_finalize_prompt(_state(human_feedback=feedback))
            assert "Human reviewer override" not in prompt

    def test_feedback_with_braces_is_inserted_verbatim(self):
        prompt = ModeratorAgent._build_finalize_prompt(_state(human_feedback="Use {vendor} B"))
        assert "Use {vendor} B" in prompt

    @pytest.mark.anyio
    async def test_decision_records_the_feedback(self):
        llm = _RecordingLLM()
        decision = await ModeratorAgent(llm_client=llm).finalize(  # type: ignore[arg-type]
            _state(current_round=1, human_feedback=f"  {FEEDBACK}  ")
        )
        assert decision.human_feedback == FEEDBACK


class TestApproveRequestValidation:
    def test_override_requires_feedback(self):
        with pytest.raises(ValidationError):
            ApproveRequest(action="override", feedback="   ")

    def test_override_with_feedback_is_valid(self):
        assert ApproveRequest(action="override", feedback=FEEDBACK).feedback == FEEDBACK

    @pytest.mark.parametrize("action", ["approve", "add_round"])
    def test_other_actions_do_not_need_feedback(self, action):
        assert ApproveRequest(action=action).feedback == ""


class TestOverrideEndToEnd:
    @pytest.mark.anyio
    async def test_override_feedback_reaches_finalize_prompt_and_decision(self):
        llm = _RecordingLLM()
        graph = DebateGraph(llm_client=llm, settings=settings)  # type: ignore[arg-type]
        state = DebateState(
            user_query="Which vendor should we pick for the rollout?", max_rounds=2, min_rounds=1
        )
        paused, decision = await graph.run(
            state.user_query, initial_state=state, hitl_mode=True, consensus_threshold=0.1
        )
        assert paused.status == "awaiting_approval" and decision is None

        approver = DebateGraph(llm_client=llm, settings=settings)  # type: ignore[arg-type]
        final_state, decision = await approver.approve(state.thread_id, action="override", feedback=FEEDBACK)

        assert final_state.termination_reason == "human_override"
        assert decision is not None and decision.human_feedback == FEEDBACK
        assert any(FEEDBACK in p for p in llm.finalize_prompts())


class TestExports:
    def _decision(self, feedback: str | None) -> FinalDecision:
        return FinalDecision(
            thread_id="t-1",
            decision="Proceed",
            rationale_summary="why",
            confidence_score=0.8,
            agreement_score=0.7,
            total_rounds=1,
            termination_reason="human_override",
            human_feedback=feedback,
        )

    def test_markdown_and_html_show_reviewer_direction(self):
        decision = self._decision("Go with <vendor> B")
        assert "Human Reviewer Direction" in render_markdown(decision)
        html = render_html(decision)
        assert "Human Reviewer Direction" in html
        assert "&lt;vendor&gt;" in html  # escaped

    def test_exports_omit_section_without_feedback(self):
        decision = self._decision(None)
        assert "Human Reviewer Direction" not in render_markdown(decision)
        assert "Human Reviewer Direction" not in render_html(decision)
