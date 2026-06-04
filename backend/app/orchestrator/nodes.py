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

# B11: threshold below which agents are considered "stuck" (drift-based early stop)
_DRIFT_EARLY_STOP_THRESHOLD: float = 0.05

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
            except asyncio.TimeoutError:
                logger.warning(
                    "agent_proposal_timeout",
                    extra={"agent": agent.name, "timeout": _PROPOSAL_TIMEOUT},
                )
                emit("agent_timeout", {
                    "round_number": ds.current_round,
                    "phase": "proposal",
                    "agent_name": agent.name,
                })
                return None
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
            except asyncio.TimeoutError:
                logger.warning(
                    "agent_critique_timeout",
                    extra={"critic": agent.name, "target": target.agent_name, "timeout": _CRITIQUE_TIMEOUT},
                )
                emit("agent_timeout", {
                    "round_number": ds.current_round,
                    "phase": "critique",
                    "agent_name": agent.name,
                })
                return None
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
            except asyncio.TimeoutError:
                logger.warning(
                    "agent_revision_timeout",
                    extra={"agent": agent.name, "timeout": _REVISION_TIMEOUT},
                )
                emit("agent_timeout", {
                    "round_number": ds.current_round,
                    "phase": "revision",
                    "agent_name": agent.name,
                })
                return None
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

        # B11: Drift-based early termination — stop when agents have stopped moving,
        # even if the agreement threshold hasn't been crossed yet.
        if should_continue and len(ds.rounds) >= 2:
            drift = ConsensusEngine().detect_position_drift(
                ds.rounds[-2].agent_outputs,
                round_data.agent_outputs,
            )
            if drift < _DRIFT_EARLY_STOP_THRESHOLD and ds.confidence_scores:
                logger.info(
                    "drift_early_termination",
                    extra={
                        "drift": round(drift, 4),
                        "round": ds.current_round,
                        "agreement_score": agreement_score,
                    },
                )
                ds.termination_reason = "consensus_reached"
                should_continue = False

        # B2 Fix: Build the HITL interrupt payload here (in convergence_node) and
        # store it in graph state.  The actual interrupt() call lives in the
        # dedicated hitl_node, which LangGraph only reaches when should_continue
        # is False AND hitl_mode is True.  This prevents the expensive
        # moderator.synthesize() call from re-running on resume.
        hitl_interrupt_payload: dict | None = None
        if state.get("hitl_mode", False) and not should_continue:
            hitl_interrupt_payload = {
                "round_number": ds.current_round,
                "agreement_score": agreement_score,
                "termination_reason": ds.termination_reason,
                "synthesis_summary": synthesis.summary,
                "options": ["approve", "override", "add_round"],
            }

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
            "awaiting_approval": False,
            "hitl_interrupt_payload": hitl_interrupt_payload,
        }

    return convergence_node


# ---------------------------------------------------------------------------
# hitl_node  (B2 fix — HITL approval lives here, not in convergence_node)
# ---------------------------------------------------------------------------

def make_hitl_node(
    emit: _Emit,
    persist_state: _PersistState = None,
) -> _NodeFn:
    """
    Human-in-the-Loop pause node.

    Only reached when hitl_mode=True and convergence_node decided to stop.
    Calls LangGraph interrupt() exactly once; on resume the node re-runs
    but interrupt() immediately returns the approval dict, so moderator.synthesize()
    is never invoked a second time (it lives in convergence_node).
    """

    async def hitl_node(state: DebateGraphState) -> dict:
        ds = state["debate_state"]
        payload = state.get("hitl_interrupt_payload") or {
            "round_number": ds.current_round,
            "agreement_score": ds.agreement_score,
            "termination_reason": ds.termination_reason,
            "synthesis_summary": "",
            "options": ["approve", "override", "add_round"],
        }

        ds.status = "awaiting_approval"
        ds.touch()
        if persist_state is not None:
            await persist_state(ds)

        # On first entry: pauses here and emits approval_required via debate_graph.py.
        # On resume:      interrupt() returns the Command(resume=...) value immediately.
        approval = interrupt(payload)

        action = approval.get("action", "approve") if isinstance(approval, dict) else "approve"
        feedback = approval.get("feedback", "") if isinstance(approval, dict) else ""

        ds.status = "in_progress"
        ds.touch()

        should_continue = False
        if action == "override":
            ds.human_feedback = feedback
            ds.termination_reason = "human_override"
        elif action == "add_round":
            ds.max_rounds += 1
            should_continue = True

        logger.info(
            "hitl_decision",
            extra={
                "thread_id": ds.thread_id,
                "action": action,
                "should_continue": should_continue,
            },
        )
        return {
            "debate_state": ds,
            "should_continue": should_continue,
            "hitl_interrupt_payload": None,  # consumed; clear from state
        }

    return hitl_node


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

        # B3 Fix: Minority report — use FINAL round only and the 0.20 threshold from spec.
        # Previous code used an all-rounds mean with a 0.10 band, which caused agents
        # who converged in later rounds to still be flagged as dissenters.
        minority: list[MinorityReportEntry] = []
        if ds.rounds:
            final_outputs = ds.rounds[-1].agent_outputs
            if final_outputs:
                final_confidences = {o.agent_name: o.confidence_score for o in final_outputs}
                mean_conf = sum(final_confidences.values()) / len(final_confidences)
                minority = [
                    MinorityReportEntry(
                        agent_name=output.agent_name,
                        final_position=output.position[:300],
                        dissent_reason=(
                            f"Confidence ({output.confidence_score:.2f}) is more than 0.20 below "
                            f"the group mean ({mean_conf:.2f}) in the final round."
                        ),
                        confidence_score=output.confidence_score,
                    )
                    for output in final_outputs
                    if output.confidence_score < mean_conf - 0.20
                ]

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
                        task = asyncio.create_task(
                            memory_store.save_memory(
                                output.agent_name,
                                ds.thread_id,
                                output.position,
                            )
                        )
                        def _on_memory_done(t: "asyncio.Task[None]") -> None:
                            if not t.cancelled() and t.exception():
                                logger.warning(
                                    "agent_memory_save_failed",
                                    extra={"error": str(t.exception())},
                                )
                        task.add_done_callback(_on_memory_done)
                        saved_names.add(output.agent_name)
                break  # only save from the last round

        return {"debate_state": ds, "final_decision": decision}

    return finalize_node
