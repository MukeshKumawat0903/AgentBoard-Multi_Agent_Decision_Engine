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

from langgraph.types import interrupt  # type: ignore[import-untyped]

from app.agents.base_agent import BaseAgent
from app.agents.moderator_agent import ModeratorAgent
from app.core.config import Settings
from app.orchestrator.lg_state import DebateGraphState
from app.schemas.final_decision import FinalDecision, MinorityReportEntry
from app.schemas.state import DebateRound, DebateState
from app.services.consensus import ConsensusEngine, SemanticConsensusEngine

_PROPOSAL_TIMEOUT: float = 15.0
_CRITIQUE_TIMEOUT: float = 15.0
_REVISION_TIMEOUT: float = 15.0

logger = logging.getLogger("agentboard.nodes")

# ---------------------------------------------------------------------------
# Type alias for the SSE emit callable
# ---------------------------------------------------------------------------
_Emit = Callable[[str, dict], None]
_NodeFn = Callable[[DebateGraphState], Awaitable[dict]]
_PersistState = Callable[["DebateState"], Awaitable[None]] | None


# ---------------------------------------------------------------------------
# proposals_node
# ---------------------------------------------------------------------------

def make_proposals_node(
    agents: dict[str, BaseAgent],
    emit: _Emit,
    persist_state: _PersistState = None,
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
        if persist_state is not None:
            await persist_state(ds)
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
    persist_state: _PersistState = None,
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
        if persist_state is not None:
            await persist_state(ds)
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
    persist_state: _PersistState = None,
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
        if persist_state is not None:
            await persist_state(ds)
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
    persist_state: _PersistState = None,
) -> _NodeFn:
    """Return an async node that scores convergence and sets should_continue."""

    # Phase 4.3: instantiate the semantic engine once at factory time so the
    # sentence-transformers model is loaded once per debate graph, not once
    # per convergence round.
    _semantic_engine: SemanticConsensusEngine | None = None
    if settings.SEMANTIC_CONSENSUS_ENABLED:
        try:
            _semantic_engine = SemanticConsensusEngine(settings.SEMANTIC_MODEL)
        except ImportError as exc:
            logger.warning(
                "semantic_consensus_unavailable",
                extra={"error": str(exc)},
            )

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

        confidence_engine = ConsensusEngine()
        # Phase 4.3: V1 confidence score is the deterministic baseline.
        # The semantic hybrid overrides it when the engine is available.
        confidence_agreement = confidence_engine.compute_agreement_score(round_data.agent_outputs)
        semantic_agreement: float | None = None
        agreement_score = confidence_agreement

        if _semantic_engine is not None and len(round_data.agent_outputs) >= 2:
            try:
                semantic_agreement = _semantic_engine.compute_semantic_similarity(
                    round_data.agent_outputs
                )
                agreement_score = _semantic_engine.compute_agreement_score(
                    round_data.agent_outputs,
                    semantic_weight=settings.SEMANTIC_CONSENSUS_WEIGHT,
                )
            except Exception as exc:
                logger.warning(
                    "semantic_consensus_failed",
                    extra={"error": str(exc)},
                )

        ds.agreement_score = agreement_score

        for output in round_data.agent_outputs:
            ds.confidence_scores[output.agent_name] = output.confidence_score

        ds.touch()
        if persist_state is not None:
            await persist_state(ds)
        logger.info(
            "round_finished",
            extra={
                "thread_id": ds.thread_id,
                "round": ds.current_round,
                "agreement_score": agreement_score,
                "should_continue": synthesis.should_continue,
            },
        )
        emit("synthesis", {
            "round_number": ds.current_round,
            "agreement_score": agreement_score,
            "should_continue": synthesis.should_continue,
            "summary": synthesis.summary,
            "agreement_areas": synthesis.agreement_areas,
            "disagreement_areas": synthesis.disagreement_areas,
            "confidence_agreement_score": confidence_agreement,
            "semantic_agreement_score": semantic_agreement,
        })

        # Mirror DebateController._should_terminate logic
        should_continue = True

        # Per-run threshold overrides the settings default
        effective_threshold = state.get("consensus_threshold") or settings.CONSENSUS_THRESHOLD

        if agreement_score >= effective_threshold:
            ds.termination_reason = "consensus_reached"
            should_continue = False
        elif ds.current_round >= ds.max_rounds:
            ds.termination_reason = "max_rounds_reached"
            should_continue = False
        elif not synthesis.should_continue and ds.confidence_scores:
            if all(s > 0.9 for s in ds.confidence_scores.values()):
                ds.termination_reason = "consensus_reached"
                should_continue = False

        # --- P4.1 Human-in-the-Loop ---
        # When hitl_mode is enabled and the convergence would end the debate,
        # pause the graph with a LangGraph interrupt and wait for approval.
        hitl_active = state.get("hitl_mode", False)
        awaiting_approval = False
        if hitl_active and not should_continue:
            ds.status = "awaiting_approval"
            ds.touch()
            if persist_state is not None:
                await persist_state(ds)

            approval = interrupt({
                "round_number": ds.current_round,
                "agreement_score": agreement_score,
                "termination_reason": ds.termination_reason,
                "synthesis_summary": synthesis.summary,
                "options": ["approve", "override", "add_round"],
            })

            action = approval.get("action", "approve") if isinstance(approval, dict) else "approve"
            feedback = approval.get("feedback", "") if isinstance(approval, dict) else ""

            ds.status = "in_progress"
            ds.touch()

            if action == "override":
                ds.human_feedback = feedback
                ds.termination_reason = "human_override"
                should_continue = False
            elif action == "add_round":
                ds.max_rounds += 1
                should_continue = True
            else:
                should_continue = False

            awaiting_approval = False

        logger.info(
            "phase_timing",
            extra={
                "phase": "convergence",
                "round": ds.current_round,
                "agreement_score": ds.agreement_score,
                "confidence_agreement_score": confidence_agreement,
                "semantic_agreement_score": semantic_agreement,
                "should_continue": should_continue,
                "elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return {
            "debate_state": ds,
            "should_continue": should_continue,
            "awaiting_approval": awaiting_approval,
        }

    return convergence_node


# ---------------------------------------------------------------------------
# finalize_node
# ---------------------------------------------------------------------------

def make_finalize_node(
    moderator: ModeratorAgent,
    emit: _Emit,
    persist_state: _PersistState = None,
    memory_store=None,
) -> _NodeFn:
    """Return an async node that asks the moderator for the FinalDecision."""

    async def finalize_node(state: DebateGraphState) -> dict:
        _t0 = time.monotonic()
        ds = state["debate_state"]

        decision = await moderator.finalize(ds)
        # Guarantee debate_trace always reflects ground-truth state
        decision = decision.model_copy(update={"debate_trace": list(ds.rounds)})

        # --- P1.5: populate richer output fields ---
        # Agent contribution scores: mean confidence across all rounds per agent
        contribution: dict[str, float] = {}
        for name in ds.confidence_scores:
            scores = [
                output.confidence_score
                for round_data in ds.rounds
                for output in round_data.agent_outputs
                if output.agent_name == name
            ]
            contribution[name] = sum(scores) / len(scores) if scores else 0.0

        # Minority report: agents whose final confidence < mean (diverged)
        if contribution:
            mean_conf = sum(contribution.values()) / len(contribution)
            minority: list[MinorityReportEntry] = []
            for round_data in reversed(ds.rounds):
                seen = {m.agent_name for m in minority}
                for output in round_data.agent_outputs:
                    if output.agent_name not in seen and output.confidence_score < mean_conf - 0.1:
                        minority.append(MinorityReportEntry(
                            agent_name=output.agent_name,
                            final_position=output.position[:300],
                            dissent_reason=(
                                f"Confidence ({output.confidence_score:.2f}) below group mean "
                                f"({mean_conf:.2f}) in final round."
                            ),
                            confidence_score=output.confidence_score,
                        ))
        else:
            minority = []

        # Key disagreements: collect from the moderator's dissenting_opinions
        # and unique critique summary points across all rounds
        key_disags: list[str] = list(decision.dissenting_opinions or [])
        for round_data in ds.rounds:
            for critique in round_data.critiques:
                for pt in critique.critique_points:
                    if pt and pt not in key_disags:
                        key_disags.append(pt)
                        if len(key_disags) >= 10:
                            break
                if len(key_disags) >= 10:
                    break

        decision = decision.model_copy(update={
            "minority_report": minority,
            "key_disagreements": key_disags[:10],  # cap at 10 items
            "agent_contribution_scores": contribution,
        })

        ds.status = (
            "converged"
            if ds.termination_reason == "consensus_reached"
            else "max_rounds_reached"
        )
        ds.touch()
        if persist_state is not None:
            await persist_state(ds)

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

        # --- P3.3 Agent Memory: save one memory entry per agent ---
        if memory_store is not None and ds.enable_agent_memory:
            for round_data in reversed(ds.rounds):
                saved_names: set[str] = set()
                for output in round_data.agent_outputs:
                    if output.agent_name not in saved_names:
                        asyncio.create_task(
                            memory_store.save_memory(
                                output.agent_name,
                                ds.thread_id,
                                output.position,
                            )
                        )
                        saved_names.add(output.agent_name)
                break  # only save from the last round

        return {"debate_state": ds, "final_decision": decision}

    return finalize_node
