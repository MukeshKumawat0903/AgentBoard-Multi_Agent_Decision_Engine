"""
LangGraph state definition for the debate workflow.

DebateGraphState is the typed state dict that flows through every node
in the LangGraph StateGraph.  It embeds the rich Pydantic DebateState
so that existing agent interfaces (which all accept DebateState) need
zero changes.
"""

from __future__ import annotations

from typing import Optional, TypedDict

from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateState


class DebateGraphState(TypedDict):
    """
    Typed state that flows through the LangGraph debate workflow.

    Fields
    ------
    debate_state:
        The full Pydantic DebateState – single source of truth for all
        round data, agent outputs, critiques, and scoring.
    should_continue:
        Routing flag written by the convergence node.
        True  → loop back to the proposals node for another round.
        False → proceed to the finalize node and exit.
    final_decision:
        Populated by the finalize node once the debate ends.
        None for all earlier nodes.
    skip_critique_phase:
        When True, the graph skips critiques and revisions each round
        (used by the 'quick' debate mode preset).
    consensus_threshold:
        Per-run override for the consensus threshold.  None means use
        the value from Settings.
    hitl_mode:
        When True, the graph routes through the hitl_node after convergence
        decides to stop, pausing for human approval before finalisation.
    awaiting_approval:
        True when the graph has emitted 'approval_required' and is waiting
        for a resume signal from the human.
    hitl_interrupt_payload:
        Payload dict built by convergence_node and consumed by hitl_node.
        Holds the data passed to LangGraph interrupt() so the hitl_node
        can re-run cleanly without re-invoking the moderator.  None when
        HITL is not active or after the hitl_node has consumed it.
    """

    debate_state: DebateState
    should_continue: bool
    final_decision: Optional[FinalDecision]
    skip_critique_phase: bool
    consensus_threshold: Optional[float]
    hitl_mode: bool
    awaiting_approval: bool
    hitl_interrupt_payload: Optional[dict]
