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

Usage::

    graph = DebateGraph(llm_client=client, settings=settings)
    state, decision = await graph.run("Should we expand to SE Asia?")
"""

from __future__ import annotations

import logging
import time

from langgraph.graph import END, START, StateGraph  # type: ignore[import-untyped]

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import BaseAgent
from app.agents.ethics_agent import EthicsAgent
from app.agents.moderator_agent import ModeratorAgent
from app.agents.risk_agent import RiskAgent
from app.agents.strategy_agent import StrategyAgent
from app.core.config import Settings
from app.orchestrator.lg_state import DebateGraphState
from app.orchestrator.nodes import (
    make_convergence_node,
    make_critiques_node,
    make_finalize_node,
    make_proposals_node,
    make_revisions_node,
)
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState
from app.services.llm_client import GroqClient


class DebateGraph:
    """
    LangGraph orchestration layer for the multi-agent debate.

    Drop-in replacement for ``DebateController``.  Accepts the same
    constructor arguments (``llm_client``, ``settings``, optional
    ``queue_list`` / ``replay_buffer`` for SSE streaming) and exposes
    a single ``run()`` coroutine that returns
    ``(DebateState, FinalDecision)``.
    """

    def __init__(
        self,
        llm_client: GroqClient,
        settings: Settings,
        queue_list: list | None = None,
        replay_buffer: list | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logging.getLogger("agentboard.orchestrator")
        self._queue_list = queue_list
        self._replay_buffer = replay_buffer

        self.agents: dict[str, BaseAgent] = {
            "Analyst": AnalystAgent(llm_client=llm_client),
            "Risk": RiskAgent(llm_client=llm_client),
            "Strategy": StrategyAgent(llm_client=llm_client),
            "Ethics": EthicsAgent(llm_client=llm_client),
        }
        self.moderator = ModeratorAgent(llm_client=llm_client)
        self._graph = self._build()

    # ------------------------------------------------------------------
    # SSE event emission (mirrors DebateController._emit exactly)
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: dict) -> None:
        """Broadcast a typed SSE event to all connected clients."""
        payload = {"type": event_type, **data}
        if self._replay_buffer is not None:
            self._replay_buffer.append(payload)
        if self._queue_list:
            for q in list(self._queue_list):  # snapshot to avoid mutation races
                q.put_nowait(payload)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build(self):
        """Assemble, wire, and compile the LangGraph StateGraph."""
        emit = self._emit
        workflow = StateGraph(DebateGraphState)

        workflow.add_node("proposals",  make_proposals_node(self.agents, emit))  # type: ignore[arg-type]
        workflow.add_node("critiques",  make_critiques_node(self.agents, emit))  # type: ignore[arg-type]
        workflow.add_node("revisions",  make_revisions_node(self.agents, emit))  # type: ignore[arg-type]
        workflow.add_node("convergence", make_convergence_node(self.moderator, self.settings, emit))  # type: ignore[arg-type]
        workflow.add_node("finalize",   make_finalize_node(self.moderator, emit))  # type: ignore[arg-type]

        # Linear edges within a round
        workflow.add_edge(START, "proposals")
        workflow.add_edge("proposals", "critiques")
        workflow.add_edge("critiques", "revisions")
        workflow.add_edge("revisions", "convergence")

        # Conditional edge: loop back or move to finalize
        workflow.add_conditional_edges(
            "convergence",
            lambda state: "proposals" if state["should_continue"] else "finalize",
            {"proposals": "proposals", "finalize": "finalize"},
        )

        workflow.add_edge("finalize", END)
        return workflow.compile()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        query: str,
        max_rounds: int | None = None,
        *,
        initial_state: DebateState | None = None,
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
        debate_state.status = "in_progress"
        debate_state.touch()

        self.logger.info(
            "debate_started",
            extra={
                "thread_id": debate_state.thread_id,
                "user_query": debate_state.user_query,
                "max_rounds": debate_state.max_rounds,
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
        }

        _debate_t0 = time.monotonic()
        result = await self._graph.ainvoke(initial_graph_state)

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
