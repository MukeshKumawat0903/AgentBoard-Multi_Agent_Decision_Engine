/**
 * DebateStreamViewer – connects to the SSE stream for a debate thread and
 * renders agents, critiques, and the final decision as they arrive.
 */

"use client";

import { useEffect, useReducer, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { connectToStream } from "@/lib/api";
import type {
  AgentOutputEvent,
  ApprovalRequiredEvent,
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
import ConfidenceDriftChart from "./ConfidenceDriftChart";
import HITLPanel from "./HITLPanel";

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
  agentStatus: Record<string, "waiting" | "working" | "done">;
  approvalRequired: ApprovalRequiredEvent | null;
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
  agentStatus: {},
  approvalRequired: null,
};

/* ------------------------------------------------------------------ */
/* Reducer                                                             */
/* ------------------------------------------------------------------ */

type Action = { event: DebateSSEEvent } | { type: "stream_error" } | { type: "clear_approval" };

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

  if ("type" in action && action.type === "clear_approval") {
    return { ...state, approvalRequired: null };
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
        agentStatus: Object.fromEntries(Object.keys(AGENT_META).map((k) => [k, "waiting"])),
      };

    case "phase_started":
      return {
        ...state,
        currentPhase: event.phase,
        rounds: state.rounds.map((r) =>
          r.round_number === event.round_number ? { ...r, phase: event.phase } : r
        ),
        // Mark all agents as working when a new phase starts
        agentStatus: Object.fromEntries(Object.keys(AGENT_META).map((k) => [k, "working"])),
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

    case "approval_required": {
      const e = event as ApprovalRequiredEvent;
      return { ...state, approvalRequired: e };
    }

    case "final_decision": {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { type, ...decision } = event as FinalDecision & { type: string };
      return { ...state, status: "done", finalDecision: decision as FinalDecision };
    }

    case "error": {
      const ev = event as { type: string; detail?: string; error?: string };
      const raw = ev.detail || ev.error || "A debate error occurred.";
      // Map known backend error codes to human-friendly messages
      const errorMessages: Record<string, string> = {
        LLMResponseError: "The AI model failed to produce a valid response. This often happens when Groq (LLM Provider) is overloaded or the prompt is too complex. Please try again.",
        LLMConnectionError: "Could not connect to the AI provider. Check that the backend is running and your API key is configured.",
        LLMRateLimitError: "Rate limit reached on the AI provider. Please wait a moment and try again.",
        DebateError: "The debate engine encountered an unrecoverable error. Please try again.",
      };
      const friendly = Object.entries(errorMessages).find(([k]) => raw.includes(k))?.[1];
      return { ...state, status: "error", error: friendly ?? raw };
    }

    default:
      return state;
  }
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */
/* ConfidenceDriftSection – collapsible chart panel                    */
/* ------------------------------------------------------------------ */

function ConfidenceDriftSection({ rounds }: { rounds: DebateRound[] }) {
  const [open, setOpen] = useState(false);
  if (rounds.length === 0) return null;
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span>📈</span> Agent Confidence Drift
        </span>
        <span className="text-gray-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4">
          <ConfidenceDriftChart rounds={rounds} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

interface Props {
  threadId: string;
}

export default function DebateStreamViewer({ threadId }: Props) {
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, initial);
  const [connStatus, setConnStatus] = useState<"connected" | "reconnecting" | "disconnected">("connected");
  const [maxReconnectsHit, setMaxReconnectsHit] = useState(false);
  const [focusedRoundIdx, setFocusedRoundIdx] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<AbortController | null>(null);

  function startStream() {
    if (controllerRef.current) controllerRef.current.abort();
    setMaxReconnectsHit(false);
    const ctrl = connectToStream(threadId, {
      onEvent: (event) => dispatch({ event }),
      onError: () => {
        setMaxReconnectsHit(true);
        setConnStatus("disconnected");
      },
      onStatusChange: setConnStatus,
    });
    controllerRef.current = ctrl;
  }

  useEffect(() => {
    startStream();
    return () => {
      controllerRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  // Keyboard J/K navigation through rounds
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (state.rounds.length === 0) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "j" || e.key === "J") {
        setFocusedRoundIdx((prev) => Math.min((prev ?? -1) + 1, state.rounds.length - 1));
      } else if (e.key === "k" || e.key === "K") {
        setFocusedRoundIdx((prev) => Math.max((prev ?? state.rounds.length) - 1, 0));
      } else if (e.key === "Escape") {
        setFocusedRoundIdx(null);
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [state.rounds]);

  // Scroll focused round into view
  const roundRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  useEffect(() => {
    if (focusedRoundIdx === null) return;
    const round = state.rounds[focusedRoundIdx];
    if (!round) return;
    const el = roundRefs.current.get(round.round_number);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusedRoundIdx, state.rounds]);

  // Auto-scroll as new events arrive while streaming
  useEffect(() => {
    if (state.status === "streaming" && focusedRoundIdx === null) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [state.rounds, state.status, focusedRoundIdx]);

  /* ---- Connection status badge ---- */
  const statusBadge = (
    <span
      aria-live="polite"
      aria-atomic="true"
      className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium ${
      connStatus === "connected"
        ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400"
        : connStatus === "reconnecting"
        ? "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400"
        : "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${
        connStatus === "connected" ? "bg-green-500 animate-pulse" :
        connStatus === "reconnecting" ? "bg-yellow-500 animate-pulse" :
        "bg-red-500"
      }`}/>
      {connStatus === "connected" ? "● Connected" : connStatus === "reconnecting" ? "↺ Reconnecting…" : "✕ Disconnected"}
    </span>
  );

  /* ---- Error ---- */
  if (state.status === "error") {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-5 px-4">
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-xl p-6 space-y-4">
          <div className="flex items-start gap-3">
            <span className="text-2xl" aria-hidden="true">⚠️</span>
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-red-700 dark:text-red-400">Debate failed</h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                {state.error ?? "An error occurred while streaming the debate."}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition"
            >
              Retry stream
            </button>
            <button
              onClick={() => router.push("/")}
              className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 transition"
            >
              Start new debate
            </button>
          </div>
        </div>
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
      {/* Query banner + connection status */}
      {state.query && (
        <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-xl p-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-blue-500 font-semibold uppercase tracking-wide mb-1">
              Debate Query
            </p>
            <p className="text-gray-800 dark:text-gray-200 leading-relaxed">{state.query}</p>
          </div>
          {state.status !== "done" && statusBadge}
        </div>
      )}

      {/* Connection lost banner */}
      {maxReconnectsHit && (
        <div className="flex items-center justify-between p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          <span>Connection lost after multiple retries.</span>
          <button
            onClick={startStream}
            className="ml-4 px-3 py-1 rounded-lg bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition"
          >
            Reconnect
          </button>
        </div>
      )}

      {/* Round progress bar */}
      {state.status === "streaming" && state.maxRounds > 0 && (
        <div className="space-y-1">
          <div
            aria-live="polite"
            aria-atomic="true"
            className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400"
          >
            <span className="font-medium">
              Round {state.currentRound} of {state.maxRounds}
              {state.currentPhase ? (
                <span className="ml-2 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 capitalize">
                  {state.currentPhase}
                </span>
              ) : null}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
              Live
            </span>
          </div>
          <div className="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-700"
              style={{ width: `${Math.min((state.currentRound / state.maxRounds) * 100, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Per-agent status rows (only during active streaming) */}
      {state.status === "streaming" && Object.keys(state.agentStatus).length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-3">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Agent status</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(state.agentStatus).map(([name, st]) => {
              const meta = AGENT_META[name as keyof typeof AGENT_META];
              return (
                <span
                  key={name}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition ${
                    st === "done"
                      ? "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400"
                      : st === "working"
                      ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400"
                      : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-500"
                  }`}
                >
                  {st === "done" ? (
                    <span className="w-3 h-3 flex items-center justify-center text-xs">✓</span>
                  ) : st === "working" ? (
                    <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin block" />
                  ) : (
                    <span className="w-3 h-3 rounded-full bg-gray-300 dark:bg-gray-600 block" />
                  )}
                  {meta?.icon ?? ""} {name}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Live rounds */}
      {state.rounds.map((round, rIdx) => {
        const synthesis = state.syntheses[round.round_number];
        const isFocused = focusedRoundIdx !== null && state.rounds[focusedRoundIdx]?.round_number === round.round_number;
        const PHASE_BADGE: Record<string, string> = {
          proposal: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
          critique: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400",
          revision: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-400",
          convergence: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400",
        };
        return (
          <div
            key={round.round_number}
            ref={(el) => { if (el) roundRefs.current.set(round.round_number, el); }}
            onClick={() => setFocusedRoundIdx(rIdx)}
            className={`bg-white dark:bg-gray-900 rounded-xl border shadow-sm overflow-hidden transition-all duration-200 cursor-pointer ${
              isFocused
                ? "border-blue-400 dark:border-blue-600 ring-2 ring-blue-200 dark:ring-blue-800"
                : "dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700"
            }`}
          >
            {/* Round header */}
            <div className="px-5 py-3 border-b dark:border-gray-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-gray-700 dark:text-gray-300 text-sm">
                  Round {round.round_number}
                </h3>
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${
                  PHASE_BADGE[round.phase] ?? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
                }`}>
                  {round.phase}
                </span>
              </div>
              {synthesis && (
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full"
                      style={{ width: `${Math.round(synthesis.agreement_score * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400 tabular-nums">
                    {Math.round(synthesis.agreement_score * 100)}% agreement
                  </span>
                </div>
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
          <ConfidenceDriftSection rounds={state.rounds} />
        </div>
      )}

      {/* Keyboard hint */}
      {state.rounds.length > 1 && (
        <p className="text-center text-xs text-gray-400 dark:text-gray-500 mt-2">
          Press <kbd className="px-1 py-0.5 rounded border border-gray-300 dark:border-gray-600 font-mono text-xs">J</kbd> / <kbd className="px-1 py-0.5 rounded border border-gray-300 dark:border-gray-600 font-mono text-xs">K</kbd> to navigate between rounds
        </p>
      )}

      <div ref={bottomRef} />

      {/* P4.1 – HITL approval overlay */}
      {state.approvalRequired && (
        <HITLPanel
          event={state.approvalRequired}
          threadId={threadId}
          onDone={() => dispatch({ type: "clear_approval" })}
        />
      )}
    </div>
  );
}
