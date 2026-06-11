/**
 * Pure reducer for DebateStreamViewer — extracted so it can be unit-tested
 * without mounting the full component or setting up SSE infrastructure.
 */

import type {
  AgentOutputEvent,
  ApprovalRequiredEvent,
  CritiqueCompletedEvent,
  DebatePhase,
  DebateRound,
  DebateSSEEvent,
  FinalDecision,
  SynthesisEvent,
  ToolCalledEvent,
} from "./types";

export interface StreamState {
  status: "connecting" | "streaming" | "done" | "error" | "cancelled";
  query: string;
  maxRounds: number;
  currentRound: number;
  currentPhase: DebatePhase | "";
  rounds: DebateRound[];
  syntheses: Record<number, SynthesisEvent>;
  finalDecision: FinalDecision | null;
  error: string | null;
  agents: string[];  // participating agents (from debate_started)
  agentStatus: Record<string, "waiting" | "working" | "done" | "timeout">;
  approvalRequired: ApprovalRequiredEvent | null;
}

export const initialStreamState: StreamState = {
  status: "connecting",
  query: "",
  maxRounds: 4,
  currentRound: 0,
  currentPhase: "",
  rounds: [],
  syntheses: {},
  finalDecision: null,
  error: null,
  agents: [],
  agentStatus: {},
  approvalRequired: null,
};

/** Build an all-"working" status map for the known participants. */
function seedWorking(agents: string[]): Record<string, "working"> {
  return Object.fromEntries(agents.map((a) => [a, "working" as const]));
}

export type StreamAction =
  | { event: DebateSSEEvent }
  | { type: "stream_error" }
  | { type: "clear_approval" };

export function ensureRound(rounds: DebateRound[], roundNumber: number): DebateRound[] {
  if (rounds.some((r) => r.round_number === roundNumber)) return rounds;
  return [
    ...rounds,
    { round_number: roundNumber, phase: "proposal", agent_outputs: [], critiques: [] },
  ];
}

export function debateStreamReducer(state: StreamState, action: StreamAction): StreamState {
  if ("type" in action && action.type === "stream_error") {
    return { ...state, status: "error", error: "Stream connection lost." };
  }
  if ("type" in action && action.type === "clear_approval") {
    return { ...state, approvalRequired: null };
  }

  const { event } = action as { event: DebateSSEEvent };

  switch (event.type) {
    case "debate_started": {
      const agents = event.agents ?? [];
      return {
        ...state,
        status: "streaming",
        query: event.user_query,
        maxRounds: event.max_rounds,
        agents,
        // Seed every participant to "working" right away so the status strip
        // is populated during round-1 proposals, before outputs arrive.
        agentStatus: seedWorking(agents),
      };
    }

    case "round_started":
      return {
        ...state,
        currentRound: event.round_number,
        rounds: ensureRound(state.rounds, event.round_number),
        // Reset to all-working using the known participant list.
        agentStatus: seedWorking(state.agents),
      };

    case "phase_started": {
      // Prefer the known participant list; fall back to agents already seen.
      const participants =
        state.agents.length > 0
          ? state.agents
          : Array.from(new Set(state.rounds.flatMap((r) => r.agent_outputs.map((o) => o.agent_name))));
      const newAgentStatus =
        participants.length > 0 ? seedWorking(participants) : state.agentStatus;
      return {
        ...state,
        currentPhase: event.phase,
        rounds: state.rounds.map((r) =>
          r.round_number === event.round_number ? { ...r, phase: event.phase } : r
        ),
        agentStatus: newAgentStatus,
      };
    }

    case "agent_output": {
      const e = event as AgentOutputEvent;
      const agentResp = {
        agent_name: e.agent_name,
        round_number: e.round_number,
        position: e.position,
        reasoning: e.reasoning,
        assumptions: e.assumptions,
        confidence_score: e.confidence_score,
        timestamp: new Date().toISOString(),
      };
      return {
        ...state,
        rounds: ensureRound(state.rounds, e.round_number).map((r) => {
          if (r.round_number !== e.round_number) return r;
          const existing = r.agent_outputs.findIndex((o) => o.agent_name === e.agent_name);
          const updated =
            existing >= 0
              ? r.agent_outputs.map((o, i) => (i === existing ? agentResp : o))
              : [...r.agent_outputs, agentResp];
          return { ...r, agent_outputs: updated };
        }),
        agentStatus: { ...state.agentStatus, [e.agent_name]: "done" },
      };
    }

    case "critique_completed": {
      const e = event as CritiqueCompletedEvent;
      const critique = {
        critic_agent: e.critic_agent,
        target_agent: e.target_agent,
        round_number: e.round_number,
        critique_points: e.critique_points,
        severity: e.severity,
        suggested_revision: null,
        confidence_score: e.confidence_score,
      };
      return {
        ...state,
        rounds: state.rounds.map((r) => {
          if (r.round_number !== e.round_number) return r;
          const alreadyPresent = r.critiques.some(
            (c) =>
              c.critic_agent === e.critic_agent &&
              c.target_agent === e.target_agent &&
              c.round_number === e.round_number
          );
          return alreadyPresent ? r : { ...r, critiques: [...r.critiques, critique] };
        }),
      };
    }

    case "synthesis": {
      const e = event as SynthesisEvent;
      return { ...state, syntheses: { ...state.syntheses, [e.round_number]: e } };
    }

    case "debate_completed":
      return { ...state, status: "streaming" };

    case "approval_required": {
      const e = event as ApprovalRequiredEvent;
      return { ...state, approvalRequired: e };
    }

    case "final_decision": {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { type, ...decision } = event as FinalDecision & { type: string };
      return { ...state, status: "done", finalDecision: decision as FinalDecision };
    }

    case "tool_called": {
      // NB3/FI1: accumulate tool calls on the current round so the UI can display them
      const e = event as ToolCalledEvent;
      const record = {
        agent_name: e.agent_name,
        tool_name: e.tool_name,
        input: e.input,
        output_snippet: e.output_snippet,
      };
      return {
        ...state,
        rounds: ensureRound(state.rounds, state.currentRound).map((r) => {
          if (r.round_number !== state.currentRound) return r;
          // Reconnects can re-deliver the same live tool_called event
          // (e.g. while Last-Event-ID catches up); skip exact duplicates
          // so the 🔧 chip list doesn't grow on every reconnect.
          const isDuplicate = (r.toolCalls ?? []).some(
            (existing) =>
              existing.agent_name === record.agent_name &&
              existing.tool_name === record.tool_name &&
              existing.input === record.input
          );
          if (isDuplicate) return r;
          return { ...r, toolCalls: [...(r.toolCalls ?? []), record] };
        }),
      };
    }

    case "agent_timeout": {
      const e = event as { type: string; agent_name: string };
      return { ...state, agentStatus: { ...state.agentStatus, [e.agent_name]: "timeout" } };
    }

    case "cancelled":
      // User cancelled — terminal state, distinct from error.
      return { ...state, status: "cancelled" };

    case "error": {
      const ev = event as { type: string; detail?: string; error?: string };
      const raw = ev.detail || ev.error || "A debate error occurred.";
      const errorMessages: Record<string, string> = {
        LLMResponseError: "The AI model failed to produce a valid response. Please try again.",
        LLMConnectionError: "Could not connect to the AI provider.",
        LLMRateLimitError: "Rate limit reached. Please wait and try again.",
        DebateError: "The debate engine encountered an unrecoverable error.",
      };
      const friendly = Object.entries(errorMessages).find(([k]) => raw.includes(k))?.[1];
      return { ...state, status: "error", error: friendly ?? raw };
    }

    default:
      return state;
  }
}
