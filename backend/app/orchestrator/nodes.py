"""
LangGraph node implementations for the debate workflow.

Each public ``make_*_node`` factory captures the agents/moderator/emit
dependencies and returns an async callable that LangGraph will invoke
with the current ``DebateGraphState``.  Nodes return a *partial* state
dict; LangGraph merges it into the running graph state.

Node pipeline
-------------
  proposals_node → critiques_node → revisions_node → convergence_node
       ↑                                                     │
       │          (should_continue = True)                  │
       └────────────────────────────────────────────────────┘
                                                             │
                            (should_continue = False)        │
                                                             ▼
                                                      finalize_node
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from app.agents.base_agent import BaseAgent
from app.agents.moderator_agent import ModeratorAgent
from app.core.config import Settings
from app.orchestrator.lg_state import DebateGraphState
from app.schemas.state import DebateRound

_PROPOSAL_TIMEOUT: float = 15.0
_CRITIQUE_TIMEOUT: float = 15.0
_REVISION_TIMEOUT: float = 15.0

logger = logging.getLogger("agentboard.nodes")

# ---------------------------------------------------------------------------
# Type alias for the SSE emit callable
# ---------------------------------------------------------------------------
_Emit = Callable[[str, dict], None]
_NodeFn = Callable[[DebateGraphState], Awaitable[dict]]


# ---------------------------------------------------------------------------
# proposals_node
# ---------------------------------------------------------------------------

def make_proposals_node(
    agents: dict[str, BaseAgent],
    emit: _Emit,
) -> _NodeFn:
    """Return an async node that starts a new round and runs all proposals."""

    async def proposals_node(state: DebateGraphState) -> dict:
        _t0 = time.monotonic()
        ds = state["debate_state"]

        # Advance the round counter and append a fresh DebateRound
        ds.current_round += 1
        round_data = DebateRound(round_number=ds.current_round)
        ds.rounds.append(round_data)
        ds.touch()

        logger.info(
            "round_started",
            extra={"thread_id": ds.thread_id, "round": ds.current_round},
        )
        emit("round_started", {
            "round_number": ds.current_round,
            "max_rounds": ds.max_rounds,
        })
        emit("phase_started", {
            "round_number": ds.current_round,
            "phase": "proposal",
        })

        async def _safe_run(agent: BaseAgent):
            try:
                result = await asyncio.wait_for(
                    agent.run(ds), timeout=_PROPOSAL_TIMEOUT
                )
                if result is not None:
                    emit("agent_output", {
                        "round_number": ds.current_round,
                        "phase": "proposal",
                        "agent_name": result.agent_name,
                        "position": result.position,
                        "reasoning": result.reasoning,
                        "confidence_score": result.confidence_score,
                        "assumptions": result.assumptions,
                    })
                return result
            except Exception as exc:
                logger.error(
                    "agent_proposal_failed",
                    extra={"agent": agent.name, "error": str(exc)},
                )
                return None

        results = await asyncio.gather(*[_safe_run(a) for a in agents.values()])
        for r in results:
            if r is not None:
                round_data.agent_outputs.append(r)

        ds.touch()
        logger.info(
            "phase_timing",
            extra={
                "phase": "proposals",
                "round": ds.current_round,
                "agents_succeeded": len(round_data.agent_outputs),
                "elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return {"debate_state": ds}

    return proposals_node


# ---------------------------------------------------------------------------
# critiques_node
# ---------------------------------------------------------------------------

def make_critiques_node(
    agents: dict[str, BaseAgent],
    emit: _Emit,
) -> _NodeFn:
    """Return an async node that runs every agent's critique in parallel."""

    async def critiques_node(state: DebateGraphState) -> dict:
        _t0 = time.monotonic()
        ds = state["debate_state"]
        round_data = ds.rounds[-1]
        round_data.phase = "critique"
        emit("phase_started", {
            "round_number": ds.current_round,
            "phase": "critique",
        })

        proposals = round_data.agent_outputs

        async def _safe_critique(agent: BaseAgent, target):
            try:
                result = await asyncio.wait_for(
                    agent.critique(ds, target), timeout=_CRITIQUE_TIMEOUT
                )
                if result is not None:
                    emit("critique_completed", {
                        "round_number": ds.current_round,
                        "critic_agent": result.critic_agent,
                        "target_agent": result.target_agent,
                        "severity": result.severity,
                        "critique_points": result.critique_points,
                        "confidence_score": result.confidence_score,
                    })
                return result
            except Exception as exc:
                logger.error(
                    "agent_critique_failed",
                    extra={
                        "critic": agent.name,
                        "target": target.agent_name,
                        "error": str(exc),
                    },
                )
                return None

        tasks = [
            _safe_critique(agent, target)
            for agent in agents.values()
            for target in proposals
            if agent.name != target.agent_name
        ]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r is not None:
                round_data.critiques.append(r)

        ds.touch()
        logger.info(
            "phase_timing",
            extra={
                "phase": "critiques",
                "round": ds.current_round,
                "critiques_produced": len(round_data.critiques),
                "elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return {"debate_state": ds}

    return critiques_node


# ---------------------------------------------------------------------------
# revisions_node
# ---------------------------------------------------------------------------

def make_revisions_node(
    agents: dict[str, BaseAgent],
    emit: _Emit,
) -> _NodeFn:
    """Return an async node that runs each agent's revision in parallel."""

    async def revisions_node(state: DebateGraphState) -> dict:
        _t0 = time.monotonic()
        ds = state["debate_state"]
        round_data = ds.rounds[-1]
        round_data.phase = "revision"
        emit("phase_started", {
            "round_number": ds.current_round,
            "phase": "revision",
        })

        # Group critiques by their target agent
        agent_critiques: dict[str, list] = {name: [] for name in agents}
        for critique in round_data.critiques:
            if critique.target_agent in agent_critiques:
                agent_critiques[critique.target_agent].append(critique)

        async def _safe_revise(agent: BaseAgent, critiques: list):
            if not critiques:
                return None
            try:
                result = await asyncio.wait_for(
                    agent.revise(ds, critiques), timeout=_REVISION_TIMEOUT
                )
                if result is not None:
                    emit("agent_output", {
                        "round_number": ds.current_round,
                        "phase": "revision",
                        "agent_name": result.agent_name,
                        "position": result.position,
                        "reasoning": result.reasoning,
                        "confidence_score": result.confidence_score,
                        "assumptions": result.assumptions,
                    })
                return result
            except Exception as exc:
                logger.error(
                    "agent_revision_failed",
                    extra={"agent": agent.name, "error": str(exc)},
                )
                return None

        tasks = [
            _safe_revise(agent, agent_critiques[name])
            for name, agent in agents.items()
        ]
        results = await asyncio.gather(*tasks)

        for name, result in zip(agents.keys(), results):
            if result is not None:
                # Replace original proposal in-place
                for j, output in enumerate(round_data.agent_outputs):
                    if output.agent_name == result.agent_name:
                        round_data.agent_outputs[j] = result
                        break
                ds.confidence_scores[name] = result.confidence_score

        ds.touch()
        logger.info(
            "phase_timing",
            extra={
                "phase": "revisions",
                "round": ds.current_round,
                "elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return {"debate_state": ds}

    return revisions_node


# ---------------------------------------------------------------------------
# convergence_node
# ---------------------------------------------------------------------------

def make_convergence_node(
    moderator: ModeratorAgent,
    settings: Settings,
    emit: _Emit,
) -> _NodeFn:
    """Return an async node that scores convergence and sets should_continue."""

    async def convergence_node(state: DebateGraphState) -> dict:
        _t0 = time.monotonic()
        ds = state["debate_state"]
        round_data = ds.rounds[-1]
        round_data.phase = "convergence"
        emit("phase_started", {
            "round_number": ds.current_round,
            "phase": "convergence",
        })

        synthesis = await moderator.synthesize(ds)
        ds.agreement_score = synthesis.agreement_score

        for output in round_data.agent_outputs:
            ds.confidence_scores[output.agent_name] = output.confidence_score

        ds.touch()
        logger.info(
            "round_finished",
            extra={
                "thread_id": ds.thread_id,
                "round": ds.current_round,
                "agreement_score": synthesis.agreement_score,
                "should_continue": synthesis.should_continue,
            },
        )
        emit("synthesis", {
            "round_number": ds.current_round,
            "agreement_score": synthesis.agreement_score,
            "should_continue": synthesis.should_continue,
            "summary": synthesis.summary,
            "agreement_areas": synthesis.agreement_areas,
            "disagreement_areas": synthesis.disagreement_areas,
        })

        # Mirror DebateController._should_terminate logic
        should_continue = True

        if synthesis.agreement_score >= settings.CONSENSUS_THRESHOLD:
            ds.termination_reason = "consensus_reached"
            should_continue = False
        elif ds.current_round >= ds.max_rounds:
            ds.termination_reason = "max_rounds_reached"
            should_continue = False
        elif not synthesis.should_continue and ds.confidence_scores:
            if all(s > 0.9 for s in ds.confidence_scores.values()):
                ds.termination_reason = "consensus_reached"
                should_continue = False

        logger.info(
            "phase_timing",
            extra={
                "phase": "convergence",
                "round": ds.current_round,
                "agreement_score": ds.agreement_score,
                "should_continue": should_continue,
                "elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return {"debate_state": ds, "should_continue": should_continue}

    return convergence_node


# ---------------------------------------------------------------------------
# finalize_node
# ---------------------------------------------------------------------------

def make_finalize_node(
    moderator: ModeratorAgent,
    emit: _Emit,
) -> _NodeFn:
    """Return an async node that asks the moderator for the FinalDecision."""

    async def finalize_node(state: DebateGraphState) -> dict:
        _t0 = time.monotonic()
        ds = state["debate_state"]

        decision = await moderator.finalize(ds)
        # Guarantee debate_trace always reflects ground-truth state
        decision = decision.model_copy(update={"debate_trace": list(ds.rounds)})

        ds.status = (
            "converged"
            if ds.termination_reason == "consensus_reached"
            else "max_rounds_reached"
        )
        ds.touch()

        logger.info(
            "debate_finalized",
            extra={
                "thread_id": ds.thread_id,
                "termination_reason": ds.termination_reason,
                "total_rounds": ds.current_round,
                "agreement_score": ds.agreement_score,
            },
        )
        emit("debate_completed", {
            "thread_id": ds.thread_id,
            "termination_reason": ds.termination_reason,
            "total_rounds": ds.current_round,
            "agreement_score": ds.agreement_score,
        })

        logger.info(
            "phase_timing",
            extra={
                "phase": "finalize",
                "round": ds.current_round,
                "elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return {"debate_state": ds, "final_decision": decision}

    return finalize_node
