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
    """

    debate_state: DebateState
    should_continue: bool
    final_decision: Optional[FinalDecision]
