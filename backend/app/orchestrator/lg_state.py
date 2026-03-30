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
        When True, the convergence node emits 'approval_required' after
        each round's convergence and the graph waits for human approval.
    awaiting_approval:
        True when the graph has emitted 'approval_required' and is waiting
        for a resume signal from the human.
    """

    debate_state: DebateState
    should_continue: bool
    final_decision: Optional[FinalDecision]
    skip_critique_phase: bool
    consensus_threshold: Optional[float]
    hitl_mode: bool
    awaiting_approval: bool
