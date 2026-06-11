/**
 * DebateStreamViewer – connects to the SSE stream for a debate thread and
 * renders agents, critiques, and the final decision as they arrive.
 */

"use client";

import { useEffect, useReducer, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { connectToStream, cancelDebate } from "@/lib/api";
import type { ApprovalRequiredEvent, DebatePhase, DebateRound, FinalDecision, SynthesisEvent } from "@/lib/types";
// B4: import domain agent metadata so domain-pack agents render with proper icons/colours
import { AGENT_META, DOMAIN_AGENT_META } from "@/lib/types";
// Reducer extracted to a separate module for unit-testability (Phase 6.1)
import {
  debateStreamReducer,
  initialStreamState,
  type StreamState,
  type StreamAction,
} from "@/lib/debateStreamReducer";

const ALL_AGENT_META = { ...AGENT_META, ...DOMAIN_AGENT_META } as Record<
  string,
  { icon: string; color?: string; lightColor?: string; role: string; name: string }
>;
import AgentCard from "./AgentCard";
import CritiqueView from "./CritiqueView";
import FinalDecisionPanel from "./FinalDecisionPanel";
import Markdown from "./Markdown";
import ConfidenceMeter from "./ConfidenceMeter";
import ConfidenceDriftChart from "./ConfidenceDriftChart";
import HITLPanel from "./HITLPanel";

/* ------------------------------------------------------------------ */
/* State and reducer — imported from debateStreamReducer (Phase 6.1)  */
/* ------------------------------------------------------------------ */
// StreamState, StreamAction, initialStreamState, debateStreamReducer
// are all defined in @/lib/debateStreamReducer and imported above.

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
  const [state, dispatch] = useReducer(debateStreamReducer, initialStreamState);
  const [connStatus, setConnStatus] = useState<"connected" | "reconnecting" | "disconnected">("connected");
  const [maxReconnectsHit, setMaxReconnectsHit] = useState(false);
  const [focusedRoundIdx, setFocusedRoundIdx] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startTimeRef = useRef<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<AbortController | null>(null);

  // Live elapsed-time meter while the debate is streaming.
  useEffect(() => {
    if (state.status !== "streaming") return;
    if (startTimeRef.current === null) startTimeRef.current = Date.now();
    const id = setInterval(() => {
      if (startTimeRef.current !== null) {
        setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [state.status]);

  const elapsedLabel = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;

  // Request server-side cancellation of the running debate.
  const handleStop = useCallback(async () => {
    setCancelling(true);
    try {
      await cancelDebate(threadId);
    } catch {
      // Ignore — the SSE stream will deliver the terminal state (cancelled/done).
    }
  }, [threadId]);

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

  /* ---- Cancelled ---- */
  if (state.status === "cancelled") {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-5 px-4">
        <div className="bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-700 rounded-xl p-6 space-y-4">
          <div className="flex items-start gap-3">
            <span className="text-2xl" aria-hidden="true">🛑</span>
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300">Debate cancelled</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
                You stopped this debate before it finished. No final decision was produced.
              </p>
            </div>
          </div>
          <button
            onClick={() => router.push("/")}
            className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition"
          >
            Start new debate
          </button>
        </div>
      </div>
    );
  }

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
          {state.status !== "done" && (
            <div className="flex flex-col items-end gap-2 shrink-0">
              {statusBadge}
              {/* Stop a running debate (server-side cancel) */}
              <button
                onClick={handleStop}
                disabled={cancelling}
                className="text-xs px-2.5 py-1 rounded-full border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {cancelling ? "Stopping…" : "■ Stop debate"}
              </button>
            </div>
          )}
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
              <span className="tabular-nums text-gray-400 dark:text-gray-500">· {elapsedLabel}</span>
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
              // B4 Fix: look up in ALL_AGENT_META (standard + domain agents)
              const meta = ALL_AGENT_META[name];
              return (
                <span
                  key={name}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition ${
                    st === "done"
                      ? "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400"
                      : st === "timeout"
                      ? "border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400"
                      : st === "working"
                      ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400"
                      : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-500"
                  }`}
                >
                  {st === "done" ? (
                    <span className="w-3 h-3 flex items-center justify-center text-xs">✓</span>
                  ) : st === "timeout" ? (
                    <span className="w-3 h-3 flex items-center justify-center text-xs">⏱</span>
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
            // Keyboard + screen-reader accessibility for round selection
            role="button"
            tabIndex={0}
            aria-pressed={isFocused}
            aria-label={`Round ${round.round_number}, ${round.phase} phase${isFocused ? " (selected)" : ""}`}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setFocusedRoundIdx(rIdx);
              }
            }}
            className={`bg-white dark:bg-gray-900 rounded-xl border shadow-sm overflow-hidden transition-all duration-200 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
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
                {round.agent_outputs.map((output) => {
                  const agentTools = round.toolCalls?.filter(
                    (tc) => tc.agent_name === output.agent_name,
                  ) ?? [];
                  return (
                    <div key={output.agent_name} className="space-y-1.5">
                      <AgentCard response={output} />
                      {/* NB3/FI1: tool activity inline under each agent card */}
                      {agentTools.map((tc, ti) => (
                        <div
                          key={ti}
                          className="text-xs bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2 flex items-start gap-2"
                        >
                          <span className="shrink-0">🔧</span>
                          <span>
                            <span className="font-medium text-amber-700 dark:text-amber-400">
                              {tc.tool_name}
                            </span>
                            {tc.output_snippet && (
                              <span className="text-gray-500 dark:text-gray-400 ml-1">
                                → {tc.output_snippet.slice(0, 120)}
                                {tc.output_snippet.length > 120 ? "…" : ""}
                              </span>
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  );
                })}
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
                  <Markdown className="text-gray-700 dark:text-gray-300">{synthesis.summary}</Markdown>
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
            {/* B5 Fix: reflect the actual termination reason instead of hardcoding "consensus reached" */}
            {state.finalDecision.termination_reason === "max_rounds_reached"
              ? "Debate complete — max rounds reached"
              : state.finalDecision.termination_reason === "human_override"
              ? "Debate complete — human override applied"
              : "Debate complete — consensus reached"}
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
