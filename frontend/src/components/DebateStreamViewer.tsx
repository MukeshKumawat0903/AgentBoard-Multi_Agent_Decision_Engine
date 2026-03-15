/**
 * DebateStreamViewer – connects to the SSE stream for a debate thread and
 * renders agents, critiques, and the final decision as they arrive.
 */

"use client";

import { useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";
import { connectToStream } from "@/lib/api";
import type {
  AgentOutputEvent,
  CritiqueCompletedEvent,
  DebatePhase,
  DebateRound,
  DebateSSEEvent,
  FinalDecision,
  SynthesisEvent,
} from "@/lib/types";
import { AGENT_META } from "@/lib/types";
import AgentCard from "./AgentCard";
import CritiqueView from "./CritiqueView";
import FinalDecisionPanel from "./FinalDecisionPanel";
import ConfidenceMeter from "./ConfidenceMeter";

/* ------------------------------------------------------------------ */
/* State shape                                                         */
/* ------------------------------------------------------------------ */

interface StreamState {
  status: "connecting" | "streaming" | "done" | "error";
  query: string;
  maxRounds: number;
  currentRound: number;
  currentPhase: DebatePhase | "";
  rounds: DebateRound[];
  syntheses: Record<number, SynthesisEvent>;
  finalDecision: FinalDecision | null;
  error: string | null;
}

const initial: StreamState = {
  status: "connecting",
  query: "",
  maxRounds: 4,
  currentRound: 0,
  currentPhase: "",
  rounds: [],
  syntheses: {},
  finalDecision: null,
  error: null,
};

/* ------------------------------------------------------------------ */
/* Reducer                                                             */
/* ------------------------------------------------------------------ */

type Action = { event: DebateSSEEvent } | { type: "stream_error" };

function ensureRound(rounds: DebateRound[], roundNumber: number): DebateRound[] {
  if (rounds.some((r) => r.round_number === roundNumber)) return rounds;
  return [
    ...rounds,
    { round_number: roundNumber, phase: "proposal", agent_outputs: [], critiques: [] },
  ];
}

function reducer(state: StreamState, action: Action): StreamState {
  if ("type" in action && action.type === "stream_error") {
    return { ...state, status: "error", error: "Stream connection lost." };
  }

  const { event } = action as { event: DebateSSEEvent };

  switch (event.type) {
    case "debate_started":
      return {
        ...state,
        status: "streaming",
        query: event.user_query,
        maxRounds: event.max_rounds,
      };

    case "round_started":
      return {
        ...state,
        currentRound: event.round_number,
        rounds: ensureRound(state.rounds, event.round_number),
      };

    case "phase_started":
      return {
        ...state,
        currentPhase: event.phase,
        rounds: state.rounds.map((r) =>
          r.round_number === event.round_number ? { ...r, phase: event.phase } : r
        ),
      };

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
        rounds: state.rounds.map((r) =>
          r.round_number === e.round_number
            ? { ...r, critiques: [...r.critiques, critique] }
            : r
        ),
      };
    }

    case "synthesis": {
      const e = event as SynthesisEvent;
      return {
        ...state,
        syntheses: { ...state.syntheses, [e.round_number]: e },
      };
    }

    case "debate_completed":
      return { ...state, status: "streaming" };

    case "final_decision": {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { type, ...decision } = event as FinalDecision & { type: string };
      return { ...state, status: "done", finalDecision: decision as FinalDecision };
    }

    case "error":
      return { ...state, status: "error", error: event.message };

    default:
      return state;
  }
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

interface Props {
  threadId: string;
}

export default function DebateStreamViewer({ threadId }: Props) {
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, initial);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const cleanup = connectToStream(threadId, {
      onEvent: (event) => dispatch({ event }),
      onError: () => dispatch({ type: "stream_error" }),
    });
    return cleanup;
  }, [threadId]);

  // Auto-scroll as new events arrive while streaming
  useEffect(() => {
    if (state.status === "streaming") {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [state.rounds, state.status]);

  /* ---- Error ---- */
  if (state.status === "error") {
    return (
      <div className="max-w-2xl mx-auto text-center py-20 space-y-4">
        <p className="text-red-600 dark:text-red-400 font-medium">
          {state.error ?? "An error occurred while streaming the debate."}
        </p>
        <button
          onClick={() => router.push("/")}
          className="px-4 py-2 rounded-lg bg-gray-800 text-white text-sm font-medium hover:bg-gray-700 transition"
        >
          Back to Home
        </button>
      </div>
    );
  }

  /* ---- Connecting ---- */
  if (state.status === "connecting") {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4 text-gray-500">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm">Connecting to debate stream…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Query banner */}
      {state.query && (
        <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
          <p className="text-xs text-blue-500 font-semibold uppercase tracking-wide mb-1">
            Debate Query
          </p>
          <p className="text-gray-800 dark:text-gray-200 leading-relaxed">{state.query}</p>
        </div>
      )}

      {/* Status bar */}
      {state.status === "streaming" && (
        <div className="flex items-center gap-3 text-sm text-gray-500 dark:text-gray-400">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            Live
          </span>
          <span>
            Round {state.currentRound} / {state.maxRounds}
            {state.currentPhase ? ` — ${state.currentPhase}` : ""}
          </span>
        </div>
      )}

      {/* Live rounds */}
      {state.rounds.map((round) => {
        const synthesis = state.syntheses[round.round_number];
        return (
          <div
            key={round.round_number}
            className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm overflow-hidden"
          >
            {/* Round header */}
            <div className="px-5 py-3 border-b dark:border-gray-800 flex items-center justify-between">
              <h3 className="font-semibold text-gray-700 dark:text-gray-300 text-sm">
                Round {round.round_number}
                {" "}
                <span className="capitalize text-gray-400 font-normal ml-1">
                  {round.phase}
                </span>
              </h3>
              {synthesis && (
                <span className="text-xs text-gray-400">
                  Agreement {(synthesis.agreement_score * 100).toFixed(0)}%
                </span>
              )}
            </div>

            {/* Agent outputs */}
            {round.agent_outputs.length > 0 && (
              <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                {round.agent_outputs.map((output) => (
                  <AgentCard key={output.agent_name} response={output} />
                ))}
              </div>
            )}

            {/* Critiques (collapsed unless there's something) */}
            {round.critiques.length > 0 && (
              <div className="px-4 pb-4 space-y-2">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  Critiques ({round.critiques.length})
                </p>
                <div className="space-y-2">
                  {round.critiques.slice(0, 6).map((c, i) => (
                    <CritiqueView key={i} critiques={[c]} />
                  ))}
                  {round.critiques.length > 6 && (
                    <p className="text-xs text-gray-400">
                      +{round.critiques.length - 6} more critiques
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Synthesis */}
            {synthesis && (
              <div className="px-4 pb-4">
                <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3 text-sm">
                  <p className="font-semibold text-yellow-700 dark:text-yellow-400 mb-1">
                    🏛️ Moderator Synthesis
                  </p>
                  <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
                    {synthesis.summary}
                  </p>
                  {synthesis.agreement_areas.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {synthesis.agreement_areas.map((a, i) => (
                        <span
                          key={i}
                          className="px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400 text-xs"
                        >
                          ✓ {a}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Streaming spinner */}
      {state.status === "streaming" && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          Agents deliberating…
        </div>
      )}

      {/* Final decision */}
      {state.finalDecision && (
        <div className="space-y-4">
          <div className="text-center text-sm font-semibold text-green-600 dark:text-green-400 flex items-center justify-center gap-2">
            <span className="w-2 h-2 bg-green-500 rounded-full" />
            Debate complete — consensus reached
          </div>
          <FinalDecisionPanel decision={state.finalDecision} />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
