"""
LangGraph-powered debate workflow graph.

Replaces ``DebateController`` as the top-level orchestration layer.
Builds and compiles a ``StateGraph`` wired with five nodes:

    START
      │
      ▼
  proposals ──► critiques ──► revisions ──► convergence
      ▲                                         │
      │   should_continue = True                │
      └─────────────────────────────────────────┘
                                                │
                    should_continue = False     │
                                                ▼
                                           finalize
                                                │
                                                ▼
                                              END

Phase 2 additions
-----------------
- AsyncSqliteSaver checkpointer: every graph state transition is persisted
    in SQLite, enabling durable recovery and replay across restarts.
- Thread config: each debate run is scoped to its thread_id so
    concurrent debates never share state.

Usage::

    graph = DebateGraph(llm_client=client, settings=settings)
    state, decision = await graph.run("Should we expand to SE Asia?")
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[import-untyped]
from langgraph.graph import END, START, StateGraph  # type: ignore[import-untyped]
from langgraph.types import Command  # type: ignore[import-untyped]

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import BaseAgent
from app.agents.ethics_agent import EthicsAgent
from app.agents.moderator_agent import ModeratorAgent
from app.agents.risk_agent import RiskAgent
from app.agents.strategy_agent import StrategyAgent
from app.agents.registry import registry
from app.core.config import Settings
from app.orchestrator.lg_state import DebateGraphState
from app.orchestrator.nodes import (
    make_convergence_node,
    make_critiques_node,
    make_finalize_node,
    make_hitl_node,
    make_proposals_node,
    make_revisions_node,
)
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import LangChainProvider


class DebateGraph:
    """
    LangGraph orchestration layer for the multi-agent debate.

    Drop-in replacement for the legacy ``DebateController``.  Accepts
    the same constructor arguments and exposes a single ``run()``
    coroutine that returns ``(DebateState, FinalDecision)``.

    Phase 2 additions
    -----------------
        - ``AsyncSqliteSaver`` checkpointer is compiled into the graph so every
      state transition is persisted per thread_id.  This enables:
      - Pause / resume for long-running debates across restarts.
      - LangGraph Studio time-travel debugging.
      - interrupt_before hooks for human-in-the-loop review (future).
    """

    def __init__(
        self,
        llm_client: LangChainProvider,
        settings: Settings,
        queue_list: list | None = None,
        replay_buffer: list | None = None,
        on_event: Callable[[dict], Coroutine[Any, Any, None]] | None = None,
        on_state_change: Callable[[DebateState], Awaitable[None]] | None = None,
        knowledge_base=None,
        memory_store=None,
        selected_agents: list[str] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logging.getLogger("agentboard.orchestrator")
        self._llm_client = llm_client
        self._queue_list = queue_list
        self._replay_buffer = replay_buffer
        self._on_event = on_event
        self._on_state_change = on_state_change
        self._knowledge_base = knowledge_base
        self._memory_store = memory_store
        self._selected_agents = list(selected_agents) if selected_agents is not None else None

        self.agents: dict[str, BaseAgent] = {}
        self._configure_participants(self._selected_agents)

    def _attach_shared_services(self) -> None:
        for agent in self.agents.values():
            agent.knowledge_base = self._knowledge_base
            agent.memory_store = self._memory_store
            agent.emit_callback = self._emit  # P3.2: wire SSE emit for tool_called events
        self.moderator.knowledge_base = self._knowledge_base
        self.moderator.memory_store = self._memory_store

    def _configure_participants(self, selected_agents: list[str] | None) -> None:
        self._selected_agents = list(selected_agents) if selected_agents is not None else None
        requested = [name for name in (selected_agents or []) if name != "Moderator"]

        if registry.is_registered("Analyst"):
            active_names = requested or [
                name for name in registry.enabled_agents() if name != "Moderator"
            ]
            self.agents = {
                name: registry.get(name, llm_client=self._llm_client)
                for name in active_names
            }
            self.moderator = registry.get("Moderator", llm_client=self._llm_client)
        else:
            fallback = {
                "Analyst": AnalystAgent(llm_client=self._llm_client),
                "Risk": RiskAgent(llm_client=self._llm_client),
                "Strategy": StrategyAgent(llm_client=self._llm_client),
                "Ethics": EthicsAgent(llm_client=self._llm_client),
            }
            self.agents = {
                name: agent
                for name, agent in fallback.items()
                if not requested or name in requested
            }
            self.moderator = ModeratorAgent(llm_client=self._llm_client)

        self._attach_shared_services()

    # ------------------------------------------------------------------
    # SSE event emission (mirrors DebateController._emit exactly)
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: dict) -> None:
        """Broadcast a typed SSE event to all connected clients."""
        payload = {"type": event_type, **data}
        if self._replay_buffer is not None:
            self._replay_buffer.append(payload)
        if self._on_event is not None:
            asyncio.create_task(self._on_event(payload))
        if self._queue_list:
            for q in list(self._queue_list):  # snapshot to avoid mutation races
                q.put_nowait(payload)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build(self, checkpointer: AsyncSqliteSaver):
        """Assemble, wire, and compile the LangGraph StateGraph with checkpointer."""
        emit = self._emit
        workflow = StateGraph(DebateGraphState)

        workflow.add_node("proposals",   make_proposals_node(self.agents, emit, self._on_state_change))   # type: ignore[arg-type]
        workflow.add_node("critiques",   make_critiques_node(self.agents, emit, self._on_state_change))   # type: ignore[arg-type]
        workflow.add_node("revisions",   make_revisions_node(self.agents, emit, self._on_state_change))   # type: ignore[arg-type]
        workflow.add_node("convergence", make_convergence_node(self.moderator, self.settings, emit, self._on_state_change))  # type: ignore[arg-type]
        # B2 Fix: HITL approval is a separate node so moderator.synthesize() is never
        # re-executed on resume — only interrupt()/approval handling re-runs.
        workflow.add_node("hitl",        make_hitl_node(emit, self._on_state_change))  # type: ignore[arg-type]
        workflow.add_node("finalize",    make_finalize_node(self.moderator, emit, self._on_state_change, self._memory_store))  # type: ignore[arg-type]

        workflow.add_edge(START, "proposals")

        # Conditional: skip critiques+revisions in 'quick' mode
        workflow.add_conditional_edges(
            "proposals",
            lambda state: "convergence" if state.get("skip_critique_phase") else "critiques",
            {"critiques": "critiques", "convergence": "convergence"},
        )
        workflow.add_edge("critiques", "revisions")
        workflow.add_edge("revisions", "convergence")

        # Convergence routes: loop back | HITL approval pause | finalize directly
        workflow.add_conditional_edges(
            "convergence",
            lambda state: (
                "proposals" if state["should_continue"]
                else ("hitl" if state.get("hitl_mode") else "finalize")
            ),
            {"proposals": "proposals", "hitl": "hitl", "finalize": "finalize"},
        )

        # After HITL approval: either add a round (loop) or finalize
        workflow.add_conditional_edges(
            "hitl",
            lambda state: "proposals" if state["should_continue"] else "finalize",
            {"proposals": "proposals", "finalize": "finalize"},
        )

        workflow.add_edge("finalize", END)
        return workflow.compile(checkpointer=checkpointer)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        query: str,
        max_rounds: int | None = None,
        *,
        initial_state: DebateState | None = None,
        consensus_threshold: float | None = None,
        skip_critique_phase: bool = False,
        hitl_mode: bool = False,
    ) -> tuple[DebateState, FinalDecision]:
        """
        Execute the full debate graph and return ``(DebateState, FinalDecision)``.

        Parameters
        ----------
        query:
            The user's problem statement (≥ 10 characters).
        max_rounds:
            Override the settings default.  ``None`` uses
            ``settings.MAX_DEBATE_ROUNDS``.
        initial_state:
            A pre-built ``DebateState`` (e.g. when the caller needs the
            ``thread_id`` *before* the graph runs).  When provided,
            ``query`` and ``max_rounds`` are ignored; the state is used
            as-is so the thread_id is preserved end-to-end.
        consensus_threshold:
            Per-run consensus threshold override. None uses settings default.
        skip_critique_phase:
            When True, skip critique and revision phases (quick mode).
        """
        if initial_state is not None:
            debate_state = initial_state
        else:
            debate_state = DebateState(
                user_query=query,
                max_rounds=(
                    max_rounds
                    if max_rounds is not None
                    else self.settings.MAX_DEBATE_ROUNDS
                ),
            )
        if debate_state.selected_agents != self._selected_agents:
            self._configure_participants(debate_state.selected_agents)
        debate_state.status = "in_progress"
        debate_state.touch()

        self.logger.info(
            "debate_started",
            extra={
                "thread_id": debate_state.thread_id,
                "user_query": debate_state.user_query,
                "max_rounds": debate_state.max_rounds,
                "skip_critique_phase": skip_critique_phase,
                "consensus_threshold": consensus_threshold,
            },
        )
        self._emit("debate_started", {
            "thread_id": debate_state.thread_id,
            "user_query": debate_state.user_query,
            "max_rounds": debate_state.max_rounds,
        })

        initial_graph_state: DebateGraphState = {
            "debate_state": debate_state,
            "should_continue": True,
            "final_decision": None,
            "skip_critique_phase": skip_critique_phase,
            "consensus_threshold": consensus_threshold,
            "hitl_mode": hitl_mode and self.settings.HITL_ENABLED,
            "awaiting_approval": False,
            "hitl_interrupt_payload": None,
        }

        # Phase 2: scope graph execution to this debate's thread_id so
        # checkpoint state is isolated across concurrent debates.
        thread_config = cast(Any, {"configurable": {"thread_id": debate_state.thread_id}})

        _debate_t0 = time.monotonic()
        async with AsyncSqliteSaver.from_conn_string(
            self.settings.CHECKPOINT_DATABASE_URL
        ) as checkpointer:
            await checkpointer.setup()
            graph = self._build(checkpointer)
            result = await graph.ainvoke(initial_graph_state, config=thread_config)

        if result.get("__interrupt__"):
            interrupt_payload = result["__interrupt__"][0].value
            if isinstance(interrupt_payload, dict):
                self._emit("approval_required", interrupt_payload)
            paused_state: DebateState = result["debate_state"]
            paused_state.status = "awaiting_approval"
            paused_state.touch()
            return paused_state, None

        final_debate_state: DebateState = result["debate_state"]
        final_decision: FinalDecision = result["final_decision"]

        self.logger.info(
            "debate_total_timing",
            extra={
                "thread_id": final_debate_state.thread_id,
                "total_rounds": final_debate_state.current_round,
                "termination_reason": final_debate_state.termination_reason,
                "total_elapsed_ms": round((time.monotonic() - _debate_t0) * 1000),
            },
        )
        return final_debate_state, final_decision

    async def resume(
        self,
        thread_id: str,
    ) -> tuple[DebateState, FinalDecision]:
        """
        Resume an interrupted debate from its last LangGraph checkpoint.

        Passes ``None`` as the graph input so LangGraph loads the latest
        persisted state for ``thread_id`` rather than restarting from the
        beginning.  The ``AsyncSqliteSaver`` checkpoint database must contain
        a checkpoint entry for this ``thread_id``.

        Raises:
            ValueError: If no checkpoint exists for the given ``thread_id``.
        """
        thread_config = cast(Any, {"configurable": {"thread_id": thread_id}})
        _t0 = time.monotonic()

        self.logger.info("debate_resume_attempt", extra={"thread_id": thread_id})
        self._emit("debate_resumed", {"thread_id": thread_id})

        async with AsyncSqliteSaver.from_conn_string(
            self.settings.CHECKPOINT_DATABASE_URL
        ) as checkpointer:
            await checkpointer.setup()

            # Verify a checkpoint exists before attempting to resume.
            checkpoint_tuple = await checkpointer.aget_tuple(thread_config)
            if checkpoint_tuple is None:
                raise ValueError(
                    f"No checkpoint found for thread_id '{thread_id}'. "
                    "Cannot resume: the debate was never checkpointed."
                )

            saved_state: dict = checkpoint_tuple.checkpoint.get("channel_values", {})
            debate_state: DebateState | None = saved_state.get("debate_state")
            if debate_state is not None and debate_state.selected_agents != self._selected_agents:
                self._configure_participants(debate_state.selected_agents)

            graph = self._build(checkpointer)
            # Passing None lets LangGraph load the state from the checkpoint
            # instead of restarting the graph from the beginning.
            result = await graph.ainvoke(None, config=thread_config)

        if result.get("__interrupt__"):
            interrupt_payload = result["__interrupt__"][0].value
            if isinstance(interrupt_payload, dict):
                self._emit("approval_required", interrupt_payload)
            paused_state: DebateState = result["debate_state"]
            paused_state.status = "awaiting_approval"
            paused_state.touch()
            return paused_state, None

        final_debate_state: DebateState = result["debate_state"]
        final_decision: FinalDecision = result["final_decision"]

        self.logger.info(
            "debate_resume_complete",
            extra={
                "thread_id": thread_id,
                "total_rounds": final_debate_state.current_round,
                "termination_reason": final_debate_state.termination_reason,
                "total_elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return final_debate_state, final_decision

    async def approve(
        self,
        thread_id: str,
        action: str = "approve",
        feedback: str = "",
    ) -> tuple[DebateState, FinalDecision]:
        """
        Resume a HITL-interrupted debate with the user's approval decision.

        Parameters
        ----------
        thread_id:
            The debate thread to resume.
        action:
            One of ``"approve"`` (accept proposed decision as-is),
            ``"override"`` (inject human feedback as a synthetic revision),
            or ``"add_round"`` (grant one extra debate round).
        feedback:
            Human feedback text used when ``action="override"``.

        Raises
        ------
        ValueError
            If no checkpoint exists or the debate is not awaiting approval.
        """
        thread_config = cast(Any, {"configurable": {"thread_id": thread_id}})
        _t0 = time.monotonic()

        self.logger.info(
            "debate_approve_attempt",
            extra={"thread_id": thread_id, "action": action},
        )

        if action not in {"approve", "override", "add_round"}:
            raise ValueError(
                f"Invalid action '{action}'. Must be 'approve', 'override', or 'add_round'."
            )

        async with AsyncSqliteSaver.from_conn_string(
            self.settings.CHECKPOINT_DATABASE_URL
        ) as checkpointer:
            await checkpointer.setup()

            checkpoint_tuple = await checkpointer.aget_tuple(thread_config)
            if checkpoint_tuple is None:
                raise ValueError(
                    f"No checkpoint found for thread_id '{thread_id}'."
                )

            saved_state: dict = checkpoint_tuple.checkpoint.get("channel_values", {})
            debate_state: DebateState | None = saved_state.get("debate_state")
            if debate_state is None or debate_state.status != "awaiting_approval":
                raise ValueError(
                    f"Debate '{thread_id}' is not currently awaiting approval."
                )

            if debate_state.selected_agents != self._selected_agents:
                self._configure_participants(debate_state.selected_agents)

            self._emit("debate_approved", {"thread_id": thread_id, "action": action})

            graph = self._build(checkpointer)
            result = await graph.ainvoke(
                Command(resume={"action": action, "feedback": feedback}),
                config=thread_config,
            )

        if result.get("__interrupt__"):
            interrupt_payload = result["__interrupt__"][0].value
            if isinstance(interrupt_payload, dict):
                self._emit("approval_required", interrupt_payload)
            paused_state: DebateState = result["debate_state"]
            paused_state.status = "awaiting_approval"
            paused_state.touch()
            return paused_state, None

        final_debate_state: DebateState = result["debate_state"]
        final_decision: FinalDecision = result["final_decision"]

        self.logger.info(
            "debate_approve_complete",
            extra={
                "thread_id": thread_id,
                "action": action,
                "total_elapsed_ms": round((time.monotonic() - _t0) * 1000),
            },
        )
        return final_debate_state, final_decision
