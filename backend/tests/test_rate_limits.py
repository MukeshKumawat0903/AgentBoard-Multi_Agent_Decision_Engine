"""
Provider rate limits: 429s are classified, calls per provider are capped,
queueing for a slot never counts against an agent's timeout, and a
rate-limited moderator no longer throws away the whole debate.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

import app.agents.moderator_agent as moderator_module
from app.agents.moderator_agent import FinalDecisionLLMOutput, ModeratorAgent, ModeratorSynthesis
from app.core.config import settings
from app.orchestrator.nodes import make_convergence_node, make_proposals_node
from app.schemas.agent_response import AgentResponse
from app.schemas.state import DebateRound, DebateState
from app.services.llm_client import LangChainProvider, _is_rate_limit_error, llm_call_slot
from app.utils.exceptions import LLMRateLimitError, LLMResponseError


class _Status429(Exception):
    status_code = 429


class DemoSchema(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_rate_limit_detected_by_status_code_class_name_or_cause_chain():
    assert _is_rate_limit_error(_Status429("slow down"))

    class RateLimitError(Exception):
        pass

    assert _is_rate_limit_error(RateLimitError("x"))
    try:
        try:
            raise _Status429("inner")
        except _Status429 as inner:
            raise RuntimeError("wrapped by langchain") from inner
    except RuntimeError as outer:
        assert _is_rate_limit_error(outer)
    assert not _is_rate_limit_error(ValueError("bad schema"))


@pytest.mark.anyio
async def test_structured_call_raises_rate_limit_error_for_429():
    llm = MagicMock()
    with patch.object(LangChainProvider, "_build_llm", return_value=llm):
        provider = LangChainProvider(provider="groq", api_key="k", model="llama-3.3-70b-versatile")
    retried = MagicMock()
    retried.ainvoke = AsyncMock(side_effect=_Status429("Rate limit reached ... org_secret"))
    llm.bind.return_value.with_structured_output.return_value.with_retry.return_value = retried

    with pytest.raises(LLMRateLimitError):
        await provider.ainvoke_structured(DemoSchema, system_prompt="s", user_prompt="u")


# ---------------------------------------------------------------------------
# Concurrency slots
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_slots_cap_concurrent_calls_per_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 2)
    active = peak = 0

    async def call():
        nonlocal active, peak
        async with llm_call_slot("groq"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(call() for _ in range(8)))
    assert peak == 2


@pytest.mark.anyio
async def test_slots_are_per_provider_and_reentrant(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 1)

    async def nested():
        async with llm_call_slot("groq"):
            async with llm_call_slot("groq"):  # same task: must not deadlock
                async with llm_call_slot("openai"):  # still re-entrant: one slot per call chain
                    return "ok"

    assert await asyncio.wait_for(nested(), timeout=2) == "ok"


@pytest.mark.anyio
async def test_zero_disables_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 0)
    active = peak = 0

    async def call():
        nonlocal active, peak
        async with llm_call_slot("groq"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(call() for _ in range(5)))
    assert peak == 5


class _SlowAgent:
    """Agent whose LLM call takes 0.3 s and goes through the client-side slot."""

    allowed_tools: list[str] = []

    def __init__(self, name: str) -> None:
        self.name = name
        self.llm_client = MagicMock(provider="groq")
        self._last_tool_calls: list = []

    async def run(self, state):
        async with llm_call_slot("groq"):  # what LangChainProvider does internally
            await asyncio.sleep(0.3)
        return AgentResponse(agent_name=self.name, round_number=state.current_round,
                             position="p", reasoning="r", confidence_score=0.8)


@pytest.mark.anyio
async def test_waiting_for_a_slot_does_not_count_against_agent_timeout(monkeypatch):
    """Three 0.3 s calls through one slot take 0.9 s in total, but each agent's
    0.5 s timeout only covers its own call."""
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 1)
    agents = {n: _SlowAgent(n) for n in ("Analyst", "Risk", "Strategy")}
    node = make_proposals_node(agents, MagicMock(), None, timeout=0.5)
    ds = DebateState(user_query="Should we expand into Singapore in Q3?")

    result = await node({"debate_state": ds})

    assert len(result["debate_state"].rounds[-1].agent_outputs) == 3


# ---------------------------------------------------------------------------
# Moderator resilience
# ---------------------------------------------------------------------------

def _state_with_outputs(with_outputs: bool = True) -> DebateState:
    outputs = [
        AgentResponse(agent_name=n, round_number=1, position="Proceed with a pilot.",
                      reasoning="r", confidence_score=0.8)
        for n in ("Analyst", "Risk")
    ] if with_outputs else []
    return DebateState(
        user_query="Should we expand into Singapore in Q3?",
        current_round=1,
        max_rounds=3,
        min_rounds=3,  # the gate cannot stop at round 1
        rounds=[DebateRound(round_number=1, agent_outputs=outputs)],
    )


@pytest.mark.anyio
async def test_moderator_waits_and_retries_when_rate_limited(monkeypatch):
    monkeypatch.setattr(moderator_module, "_RATE_LIMIT_BACKOFF_SECONDS", (0.0, 0.0))
    client = MagicMock()
    client.ainvoke_structured = AsyncMock(side_effect=[
        LLMRateLimitError("429"),
        LLMRateLimitError("429"),
        FinalDecisionLLMOutput(decision="Proceed", rationale_summary="why",
                               confidence_score=0.8, agreement_score=0.8),
    ])

    decision = await ModeratorAgent(llm_client=client).finalize(_state_with_outputs())

    assert decision.decision == "Proceed"
    assert client.ainvoke_structured.await_count == 3


@pytest.mark.anyio
async def test_moderator_gives_up_after_the_backoff_budget(monkeypatch):
    monkeypatch.setattr(moderator_module, "_RATE_LIMIT_BACKOFF_SECONDS", (0.0,))
    client = MagicMock()
    client.ainvoke_structured = AsyncMock(side_effect=LLMRateLimitError("429"))

    with pytest.raises(LLMRateLimitError):
        await ModeratorAgent(llm_client=client).synthesize(_state_with_outputs())
    assert client.ainvoke_structured.await_count == 2


@pytest.mark.anyio
async def test_moderator_does_not_retry_other_errors(monkeypatch):
    monkeypatch.setattr(moderator_module, "_RATE_LIMIT_BACKOFF_SECONDS", (0.0, 0.0))
    client = MagicMock()
    client.ainvoke_structured = AsyncMock(side_effect=LLMResponseError("bad json"))

    with pytest.raises(LLMResponseError):
        await ModeratorAgent(llm_client=client).synthesize(_state_with_outputs())
    assert client.ainvoke_structured.await_count == 1


def _gate_settings() -> MagicMock:
    from tests.test_orchestrator import _mock_settings
    return _mock_settings()


@pytest.mark.anyio
async def test_failed_synthesis_does_not_end_a_round_that_has_agent_output():
    moderator = MagicMock()
    moderator.synthesize = AsyncMock(side_effect=LLMRateLimitError("429"))
    emit = MagicMock()
    node = make_convergence_node(moderator, _gate_settings(), emit, AsyncMock())

    result = await node({"debate_state": _state_with_outputs(), "should_continue": True, "final_decision": None})

    assert result["should_continue"] is True  # round 1 of 3, the debate goes on
    synthesis_events = [c.args[1] for c in emit.call_args_list if c.args[0] == "synthesis"]
    assert "could not summarise" in synthesis_events[0]["summary"]


@pytest.mark.anyio
async def test_failed_synthesis_with_no_agent_output_still_fails_the_debate():
    moderator = MagicMock()
    moderator.synthesize = AsyncMock(side_effect=LLMResponseError("invalid api key"))
    node = make_convergence_node(moderator, _gate_settings(), MagicMock(), AsyncMock())

    with pytest.raises(LLMResponseError):
        await node({"debate_state": _state_with_outputs(with_outputs=False),
                    "should_continue": True, "final_decision": None})


def test_synthesis_placeholder_is_a_valid_schema():
    assert ModeratorSynthesis(summary="x", agreement_score=0.0, should_continue=True).agreement_areas == []
