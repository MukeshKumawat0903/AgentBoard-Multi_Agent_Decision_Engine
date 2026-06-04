"""
Phase 6.4 — Decision evaluation service tests.

Tests evaluate_decision: correct schema, four dimension scores,
graceful handling of LLM failures, and that the DB caches results.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.final_decision import FinalDecision


def _make_decision() -> FinalDecision:
    return FinalDecision(
        thread_id="thread-eval-001",
        query="Should we expand to SE Asia?",
        decision="Proceed with phased rollout.",
        rationale_summary="Data supports cautious growth.",
        confidence_score=0.82,
        agreement_score=0.78,
        risk_flags=["Currency volatility"],
        alternatives=["Delay one quarter"],
        total_rounds=2,
        termination_reason="consensus_reached",
    )


def _mock_eval_output():
    from app.services.evaluator import EvaluationLLMOutput  # noqa: PLC0415
    return EvaluationLLMOutput(
        completeness=0.9,
        consistency=0.85,
        actionability=0.75,
        risk_awareness=0.88,
        reasoning="Good overall decision quality.",
    )


class TestEvaluationService:

    @pytest.mark.anyio
    async def test_evaluate_returns_evaluation_result_schema(self):
        from app.services.evaluator import evaluate_decision, EvaluationResult  # noqa: PLC0415

        mock_client = MagicMock()
        mock_client.ainvoke_structured = AsyncMock(return_value=_mock_eval_output())

        result = await evaluate_decision(_make_decision(), llm_client=mock_client)

        assert isinstance(result, EvaluationResult)
        assert result.thread_id == "thread-eval-001"

    @pytest.mark.anyio
    async def test_overall_score_is_mean_of_four_dimensions(self):
        from app.services.evaluator import evaluate_decision  # noqa: PLC0415

        mock_client = MagicMock()
        mock_client.ainvoke_structured = AsyncMock(return_value=_mock_eval_output())

        result = await evaluate_decision(_make_decision(), llm_client=mock_client)

        expected_overall = (0.9 + 0.85 + 0.75 + 0.88) / 4
        assert result.overall == pytest.approx(expected_overall, abs=0.01)

    @pytest.mark.anyio
    async def test_all_four_dimensions_in_0_1_range(self):
        from app.services.evaluator import evaluate_decision  # noqa: PLC0415

        mock_client = MagicMock()
        mock_client.ainvoke_structured = AsyncMock(return_value=_mock_eval_output())

        result = await evaluate_decision(_make_decision(), llm_client=mock_client)

        for dim in (result.completeness, result.consistency, result.actionability, result.risk_awareness):
            assert 0.0 <= dim <= 1.0

    @pytest.mark.anyio
    async def test_evaluated_at_is_set(self):
        from app.services.evaluator import evaluate_decision  # noqa: PLC0415

        mock_client = MagicMock()
        mock_client.ainvoke_structured = AsyncMock(return_value=_mock_eval_output())

        result = await evaluate_decision(_make_decision(), llm_client=mock_client)

        assert result.evaluated_at is not None
        assert len(result.evaluated_at) > 0

    @pytest.mark.anyio
    async def test_llm_failure_raises_or_returns_gracefully(self):
        from app.services.evaluator import evaluate_decision  # noqa: PLC0415
        from app.utils.exceptions import LLMResponseError  # noqa: PLC0415

        mock_client = MagicMock()
        mock_client.ainvoke_structured = AsyncMock(
            side_effect=LLMResponseError("LLM unavailable")
        )

        with pytest.raises(LLMResponseError):
            await evaluate_decision(_make_decision(), llm_client=mock_client)


class TestEvaluationCaching:
    """Verify that the evaluate endpoint returns cached result on second call."""

    @pytest.mark.anyio
    async def test_cached_result_returned_from_db(self):
        import aiosqlite  # noqa: PLC0415
        from app.db.crud import save_evaluation, get_evaluation_json  # noqa: PLC0415
        from app.services.evaluator import EvaluationResult  # noqa: PLC0415
        import json  # noqa: PLC0415

        result = EvaluationResult(
            thread_id="cache-001",
            completeness=0.9,
            consistency=0.8,
            actionability=0.85,
            risk_awareness=0.88,
            overall=0.8575,
            reasoning="Cached.",
            evaluated_at="2026-06-04T10:00:00",
        )

        async with aiosqlite.connect(":memory:") as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS decisions (
                    thread_id TEXT PRIMARY KEY,
                    query TEXT,
                    decision_json TEXT,
                    evaluation_json TEXT,
                    created_at TEXT
                )"""
            )
            await db.execute(
                "INSERT INTO decisions (thread_id, query, decision_json, created_at) VALUES (?, ?, ?, ?)",
                ("cache-001", "Q?", "{}", "2026-06-04"),
            )
            await db.commit()
            await save_evaluation(db, "cache-001", result.model_dump_json())
            cached_json = await get_evaluation_json(db, "cache-001")

        assert cached_json is not None
        parsed = EvaluationResult.model_validate_json(cached_json)
        assert parsed.thread_id == "cache-001"
        assert parsed.overall == pytest.approx(0.8575, abs=0.001)
