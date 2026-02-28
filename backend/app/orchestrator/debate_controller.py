"""
Debate Controller – Orchestrates the multi-agent debate state machine.

Manages the full lifecycle: proposals → critiques → revisions → convergence.
"""

from __future__ import annotations

import asyncio
import logging

from app.agents.analyst_agent import AnalystAgent
from app.agents.base_agent import BaseAgent
from app.agents.ethics_agent import EthicsAgent
from app.agents.moderator_agent import ModeratorAgent, ModeratorSynthesis
from app.agents.risk_agent import RiskAgent
from app.agents.strategy_agent import StrategyAgent
from app.core.config import Settings
from app.schemas.agent_response import AgentResponse, CritiqueResponse
from app.schemas.final_decision import FinalDecision
from app.schemas.state import DebateRound, DebateState
from app.services.llm_client import GroqClient

_PROPOSAL_TIMEOUT: float = 30.0
_CRITIQUE_TIMEOUT: float = 30.0
_REVISION_TIMEOUT: float = 30.0


class DebateController:
    """
    State machine that orchestrates the multi-agent debate.

    Lifecycle:
    1. initialize_state(query) -> DebateState
    2. execute() -> FinalDecision
       - Internally runs: proposals → cross-examination → revisions →
         convergence check → (loop or finalize)

    Sequential phases, parallel execution within each phase.
    Failed individual agent calls are logged and skipped (graceful degradation).
    State is stored in-memory; swap for Redis in a future phase.
    """

    def __init__(self, llm_client: GroqClient, settings: Settings) -> None:
        self.agents: dict[str, BaseAgent] = self._create_agents(llm_client)
        self.moderator: ModeratorAgent = ModeratorAgent(llm_client=llm_client)
        self.state: DebateState | None = None
        self.settings = settings
        self.logger = logging.getLogger("agentboard.orchestrator")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _create_agents(self, llm_client: GroqClient) -> dict[str, BaseAgent]:
        """Instantiate the 4 debate agents (Analyst, Risk, Strategy, Ethics)."""
        return {
            "Analyst": AnalystAgent(llm_client=llm_client),
            "Risk": RiskAgent(llm_client=llm_client),
            "Strategy": StrategyAgent(llm_client=llm_client),
            "Ethics": EthicsAgent(llm_client=llm_client),
        }

    async def initialize_state(
        self,
        query: str,
        max_rounds: int | None = None,
    ) -> DebateState:
        """Create a fresh DebateState for a new debate session."""
        self.state = DebateState(
            user_query=query,
            max_rounds=max_rounds if max_rounds is not None else self.settings.MAX_DEBATE_ROUNDS,
        )
        self.logger.info(
            "debate_initialized",
            extra={"thread_id": self.state.thread_id, "max_rounds": self.state.max_rounds},
        )
        return self.state

    async def execute(self) -> FinalDecision:
        """Run the full debate loop until convergence or max rounds are exhausted."""
        if self.state is None:
            raise RuntimeError("Call initialize_state() before execute().")

        state = self.state
        state.status = "in_progress"
        state.touch()

        self.logger.info("debate_started", extra={"thread_id": state.thread_id})

        while True:
            state.current_round += 1
            round_data = DebateRound(round_number=state.current_round)
            state.rounds.append(round_data)
            state.touch()

            self.logger.info(
                "round_started",
                extra={"thread_id": state.thread_id, "round": state.current_round},
            )

            # Phase 1 – Independent proposals
            round_data.phase = "proposal"
            await self._run_proposals(state)

            # Phase 2 – Cross-examination
            round_data.phase = "critique"
            await self._run_cross_examination(state)

            # Phase 3 – Revisions
            round_data.phase = "revision"
            await self._run_revisions(state)

            # Phase 4 – Convergence check
            round_data.phase = "convergence"
            synthesis = await self._run_convergence_check(state)

            self.logger.info(
                "round_finished",
                extra={
                    "thread_id": state.thread_id,
                    "round": state.current_round,
                    "agreement_score": synthesis.agreement_score,
                    "should_continue": synthesis.should_continue,
                },
            )

            if self._should_terminate(state, synthesis):
                break

        return await self._finalize(state)

    # ------------------------------------------------------------------
    # Phase helpers
    # ------------------------------------------------------------------

    async def _run_proposals(self, state: DebateState) -> list[AgentResponse]:
        """Call every debate agent's run() in parallel; skip on failure."""

        async def _safe_run(agent: BaseAgent) -> AgentResponse | None:
            try:
                return await asyncio.wait_for(
                    agent.run(state), timeout=_PROPOSAL_TIMEOUT
                )
            except Exception as exc:
                self.logger.error(
                    "agent_proposal_failed",
                    extra={"agent": agent.name, "error": str(exc)},
                )
                return None

        results = await asyncio.gather(*[_safe_run(a) for a in self.agents.values()])

        round_data = state.rounds[-1]
        outputs: list[AgentResponse] = []
        for r in results:
            if r is not None:
                round_data.agent_outputs.append(r)
                outputs.append(r)

        state.touch()
        return outputs

    async def _run_cross_examination(self, state: DebateState) -> list[CritiqueResponse]:
        """Every agent critiques every other agent's proposal in parallel."""
        round_data = state.rounds[-1]
        proposals = round_data.agent_outputs

        async def _safe_critique(
            agent: BaseAgent, target: AgentResponse
        ) -> CritiqueResponse | None:
            try:
                return await asyncio.wait_for(
                    agent.critique(state, target), timeout=_CRITIQUE_TIMEOUT
                )
            except Exception as exc:
                self.logger.error(
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
            for agent in self.agents.values()
            for target in proposals
            if agent.name != target.agent_name
        ]
        results = await asyncio.gather(*tasks)

        for r in results:
            if r is not None:
                round_data.critiques.append(r)

        state.touch()
        return [r for r in results if r is not None]

    async def _run_revisions(self, state: DebateState) -> list[AgentResponse]:
        """Each agent revises its position based on critiques directed at it."""
        round_data = state.rounds[-1]

        # Group critiques by target agent
        agent_critiques: dict[str, list[CritiqueResponse]] = {
            name: [] for name in self.agents
        }
        for critique in round_data.critiques:
            if critique.target_agent in agent_critiques:
                agent_critiques[critique.target_agent].append(critique)

        async def _safe_revise(
            agent: BaseAgent, critiques: list[CritiqueResponse]
        ) -> AgentResponse | None:
            if not critiques:
                return None
            try:
                return await asyncio.wait_for(
                    agent.revise(state, critiques), timeout=_REVISION_TIMEOUT
                )
            except Exception as exc:
                self.logger.error(
                    "agent_revision_failed",
                    extra={"agent": agent.name, "error": str(exc)},
                )
                return None

        tasks = [
            _safe_revise(agent, agent_critiques[name])
            for name, agent in self.agents.items()
        ]
        results = await asyncio.gather(*tasks)

        revised: list[AgentResponse] = []
        for name, result in zip(self.agents.keys(), results):
            if result is not None:
                # Replace original proposal with the revised version in-place
                for j, output in enumerate(round_data.agent_outputs):
                    if output.agent_name == result.agent_name:
                        round_data.agent_outputs[j] = result
                        break
                revised.append(result)
                state.confidence_scores[name] = result.confidence_score

        state.touch()
        return revised

    async def _run_convergence_check(self, state: DebateState) -> ModeratorSynthesis:
        """Moderator synthesises the round and updates state's agreement score."""
        synthesis = await self.moderator.synthesize(state)
        state.agreement_score = synthesis.agreement_score

        for output in state.rounds[-1].agent_outputs:
            state.confidence_scores[output.agent_name] = output.confidence_score

        state.touch()
        self.logger.info(
            "convergence_check",
            extra={
                "thread_id": state.thread_id,
                "round": state.current_round,
                "agreement_score": synthesis.agreement_score,
                "should_continue": synthesis.should_continue,
            },
        )
        return synthesis

    # ------------------------------------------------------------------
    # Termination & finalisation
    # ------------------------------------------------------------------

    def _should_terminate(
        self, state: DebateState, synthesis: ModeratorSynthesis
    ) -> bool:
        """
        Return True (and set state.termination_reason) when the debate should end.

        Terminates when:
        - agreement_score reaches the consensus threshold, OR
        - current_round has hit max_rounds, OR
        - moderator says stop AND all agents report > 0.9 confidence
        """
        if synthesis.agreement_score >= self.settings.CONSENSUS_THRESHOLD:
            state.termination_reason = "consensus_reached"
            self.logger.info(
                "termination_consensus",
                extra={
                    "thread_id": state.thread_id,
                    "agreement_score": synthesis.agreement_score,
                },
            )
            return True

        if state.current_round >= state.max_rounds:
            state.termination_reason = "max_rounds_reached"
            self.logger.info(
                "termination_max_rounds",
                extra={"thread_id": state.thread_id, "round": state.current_round},
            )
            return True

        # All agents highly confident and moderator no longer requests continuation
        if not synthesis.should_continue and state.confidence_scores:
            if all(s > 0.9 for s in state.confidence_scores.values()):
                state.termination_reason = "consensus_reached"
                self.logger.info(
                    "termination_high_confidence",
                    extra={"thread_id": state.thread_id},
                )
                return True

        return False

    async def _finalize(self, state: DebateState) -> FinalDecision:
        """Ask the moderator for the FinalDecision and close out the state."""
        decision = await self.moderator.finalize(state)

        # Guarantee the debate trace is always populated from ground-truth state
        decision = decision.model_copy(update={"debate_trace": list(state.rounds)})

        state.status = (
            "converged"
            if state.termination_reason == "consensus_reached"
            else "max_rounds_reached"
        )
        state.touch()

        self.logger.info(
            "debate_finalized",
            extra={
                "thread_id": state.thread_id,
                "termination_reason": state.termination_reason,
                "total_rounds": state.current_round,
                "agreement_score": state.agreement_score,
            },
        )
        return decision
