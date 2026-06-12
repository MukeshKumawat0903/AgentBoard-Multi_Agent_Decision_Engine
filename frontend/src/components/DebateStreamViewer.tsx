/**
 * DebateStreamViewer – connects to the SSE stream for a debate thread and
 * renders agents, critiques, and the final decision as they arrive.
 *
 * Rounds render along a vertical timeline spine; a persistent presence strip
 * shows each agent's live status; the consensus moment lands with a result
 * banner and count-up scores.
 */

"use client";

import { useEffect, useReducer, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  CircleStop,
  Clock,
  FileText,
  Loader2,
  PartyPopper,
  RotateCw,
  TrendingUp,
  UserCheck,
  Wifi,
  WifiOff,
  Wrench,
} from "lucide-react";
import { connectToStream, cancelDebate } from "@/lib/api";
import type { DebateRound, FinalDecision } from "@/lib/types";
import {
  debateStreamReducer,
  initialStreamState,
} from "@/lib/debateStreamReducer";
import AgentCard from "./AgentCard";
import CritiqueView from "./CritiqueView";
import FinalDecisionPanel from "./FinalDecisionPanel";
import Markdown from "./Markdown";
import ConfidenceDriftChart from "./ConfidenceDriftChart";
import HITLPanel from "./HITLPanel";
import AgentAvatar, { agentColor } from "./ui/AgentAvatar";
import Badge, { type BadgeTone } from "./ui/Badge";
import Button from "./ui/Button";
import CollapsibleSection from "./ui/CollapsibleSection";
import useCountUp from "@/lib/useCountUp";

/* ------------------------------------------------------------------ */
/* Phase styling — one source of truth for badges and timeline nodes   */
/* ------------------------------------------------------------------ */

const PHASE_META: Record<string, { tone: BadgeTone; node: string }> = {
  proposal: { tone: "info", node: "bg-accent-500" },
  critique: { tone: "warning", node: "bg-amber-500" },
  revision: { tone: "violet", node: "bg-violet-500" },
  convergence: { tone: "success", node: "bg-green-500" },
};

/* ------------------------------------------------------------------ */
/* ConfettiBurst – one-shot celebratory particles (reduced-motion safe  */
/* via the global media query that zeroes animation durations).        */
/* ------------------------------------------------------------------ */

const CONFETTI_COLORS = ["#6366F1", "#8B5CF6", "#22C55E", "#F59E0B", "#EC4899", "#3B82F6"];

function ConfettiBurst() {
  const pieces = Array.from({ length: 14 }, (_, i) => {
    const angle = (i / 14) * 2 * Math.PI;
    const dist = 70 + (i % 3) * 25;
    return {
      dx: `${Math.round(Math.cos(angle) * dist)}px`,
      dy: `${Math.round(Math.sin(angle) * dist * 0.7) - 30}px`,
      color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
      delay: `${(i % 4) * 60}ms`,
    };
  });
  return (
    <span aria-hidden="true" className="absolute inset-0 overflow-hidden pointer-events-none">
      {pieces.map((p, i) => (
        <span
          key={i}
          className="absolute left-1/2 top-1/2 w-1.5 h-1.5 rounded-[2px]"
          style={{
            backgroundColor: p.color,
            ["--dx" as string]: p.dx,
            ["--dy" as string]: p.dy,
            animation: `confetti-burst 1s ease-out ${p.delay} both`,
          }}
        />
      ))}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* ResultBanner – the consensus moment, with count-up scores           */
/* ------------------------------------------------------------------ */

function ResultBanner({ decision }: { decision: FinalDecision }) {
  const agreement = useCountUp(decision.agreement_score * 100);
  const confidence = useCountUp(decision.confidence_score * 100);
  const isConsensus =
    decision.termination_reason !== "max_rounds_reached" &&
    decision.termination_reason !== "human_override";

  const { Icon, headline, classes } =
    decision.termination_reason === "max_rounds_reached"
      ? {
          Icon: Clock,
          headline: `Debate complete — max rounds reached after ${decision.total_rounds}`,
          classes:
            "from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 text-amber-800 dark:text-amber-300 ring-amber-200 dark:ring-amber-800",
        }
      : decision.termination_reason === "human_override"
      ? {
          Icon: UserCheck,
          headline: "Debate complete — human override applied",
          classes:
            "from-violet-50 to-purple-50 dark:from-violet-900/20 dark:to-purple-900/20 text-violet-800 dark:text-violet-300 ring-violet-200 dark:ring-violet-800",
        }
      : {
          Icon: PartyPopper,
          headline: `Consensus reached after ${decision.total_rounds} round${decision.total_rounds !== 1 ? "s" : ""}`,
          classes:
            "from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20 text-green-800 dark:text-green-300 ring-green-200 dark:ring-green-800",
        };

  return (
    <div
      className={`relative rounded-2xl bg-gradient-to-r ring-1 px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-6 animate-scaleIn ${classes}`}
    >
      {isConsensus && <ConfettiBurst />}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <Icon className="w-6 h-6 shrink-0" aria-hidden="true" />
        <p className="font-semibold text-sm sm:text-base">{headline}</p>
      </div>
      <div className="flex items-center gap-5 shrink-0 tabular-nums">
        <span className="text-center">
          <span className="block text-xl font-bold leading-tight">{Math.round(agreement)}%</span>
          <span className="block text-[10px] uppercase tracking-wide opacity-70">Agreement</span>
        </span>
        <span className="text-center">
          <span className="block text-xl font-bold leading-tight">{Math.round(confidence)}%</span>
          <span className="block text-[10px] uppercase tracking-wide opacity-70">Confidence</span>
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

interface Props {
  threadId: string;
  onQuery?: (query: string) => void;
}

export default function DebateStreamViewer({ threadId, onQuery }: Props) {
  const router = useRouter();
  const [state, dispatch] = useReducer(debateStreamReducer, initialStreamState);
  const [connStatus, setConnStatus] = useState<"connected" | "reconnecting" | "disconnected">("connected");
  const [maxReconnectsHit, setMaxReconnectsHit] = useState(false);
  const [focusedRoundIdx, setFocusedRoundIdx] = useState<number | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
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

  // Surface the debate query to the parent (for the breadcrumb).
  useEffect(() => {
    if (state.query) onQuery?.(state.query);
  }, [state.query, onQuery]);

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

  // When the debate finishes, jump to the top so the user lands on the decision.
  const scrolledToDecisionRef = useRef(false);
  useEffect(() => {
    if (state.status === "done" && !scrolledToDecisionRef.current) {
      scrolledToDecisionRef.current = true;
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [state.status]);

  /* ---- Connection status badge ---- */
  const statusBadge = (
    <span aria-live="polite" aria-atomic="true">
      <Badge
        tone={connStatus === "connected" ? "success" : connStatus === "reconnecting" ? "warning" : "danger"}
      >
        {connStatus === "connected" ? (
          <Wifi className="w-3 h-3" aria-hidden="true" />
        ) : connStatus === "reconnecting" ? (
          <RotateCw className="w-3 h-3 animate-spin" aria-hidden="true" />
        ) : (
          <WifiOff className="w-3 h-3" aria-hidden="true" />
        )}
        {connStatus === "connected" ? "Connected" : connStatus === "reconnecting" ? "Reconnecting…" : "Disconnected"}
      </Badge>
    </span>
  );

  /* ---- Cancelled ---- */
  if (state.status === "cancelled") {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-5 px-4">
        <div className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-6 space-y-4">
          <div className="flex items-start gap-3">
            <CircleStop className="w-7 h-7 text-gray-400 shrink-0" aria-hidden="true" />
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300">Debate cancelled</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
                You stopped this debate before it finished. No final decision was produced.
              </p>
            </div>
          </div>
          <Button variant="primary" onClick={() => router.push("/")}>
            Start new debate
          </Button>
        </div>
      </div>
    );
  }

  /* ---- Error ---- */
  if (state.status === "error") {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-5 px-4">
        <div className="bg-red-50 dark:bg-red-950/30 ring-1 ring-red-200 dark:ring-red-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-7 h-7 text-red-500 shrink-0" aria-hidden="true" />
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-red-700 dark:text-red-400">Debate failed</h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                {state.error ?? "An error occurred while streaming the debate."}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button variant="danger" onClick={() => window.location.reload()}>
              Retry stream
            </Button>
            <Button variant="secondary" onClick={() => router.push("/")}>
              Start new debate
            </Button>
          </div>
        </div>
      </div>
    );
  }

  /* ---- Connecting ---- */
  if (state.status === "connecting") {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4 text-gray-500">
        <Loader2 className="w-8 h-8 text-accent-500 animate-spin" aria-hidden="true" />
        <p className="text-sm">Connecting to debate stream…</p>
      </div>
    );
  }

  const isDone = state.status === "done" && !!state.finalDecision;
  const totalCritiques = state.rounds.reduce((n, r) => n + r.critiques.length, 0);

  /* ---- Rounds along the timeline spine ---- */
  const renderRounds = (
    <div className="relative space-y-6">
      {/* Spine */}
      {state.rounds.length > 0 && (
        <span
          aria-hidden="true"
          className="absolute left-[15px] top-4 bottom-4 w-px bg-line-strong"
        />
      )}
      {state.rounds.map((round: DebateRound, rIdx: number) => {
        const synthesis = state.syntheses[round.round_number];
        const isFocused =
          focusedRoundIdx !== null && state.rounds[focusedRoundIdx]?.round_number === round.round_number;
        const isActiveRound = state.status === "streaming" && rIdx === state.rounds.length - 1;
        const phase = PHASE_META[round.phase] ?? { tone: "neutral" as BadgeTone, node: "bg-gray-400" };
        return (
          <div key={round.round_number} className="relative flex gap-4">
            {/* Timeline node */}
            <div className="shrink-0 w-8 flex justify-center pt-4">
              <span
                aria-hidden="true"
                className={`relative z-10 w-8 h-8 rounded-full text-white text-xs font-bold flex items-center justify-center
                            ring-4 ring-surface ${phase.node} ${isActiveRound ? "animate-pulse" : ""}`}
              >
                {round.round_number}
              </span>
            </div>

            {/* Round card */}
            <div
              ref={(el) => { if (el) roundRefs.current.set(round.round_number, el); }}
              onClick={() => setFocusedRoundIdx(rIdx)}
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
              className={`flex-1 min-w-0 rounded-2xl bg-surface-raised shadow-card overflow-hidden transition-all duration-200 cursor-pointer
                          focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 animate-slideUpIn ${
                isFocused
                  ? "ring-2 ring-accent-400 dark:ring-accent-600"
                  : "ring-1 ring-black/5 dark:ring-white/10 hover:ring-line-strong"
              }`}
            >
              {/* Round header */}
              <div className="px-5 py-3 border-b border-line flex items-center justify-between sticky top-14 bg-surface-raised/95 backdrop-blur z-[5]">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-gray-700 dark:text-gray-300 text-sm">
                    Round {round.round_number}
                  </h3>
                  <Badge tone={phase.tone} className="capitalize">{round.phase}</Badge>
                </div>
                {synthesis && (
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-green-500 rounded-full transition-all duration-500"
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
                  {round.agent_outputs.map((output, oIdx) => {
                    const agentTools = round.toolCalls?.filter(
                      (tc) => tc.agent_name === output.agent_name,
                    ) ?? [];
                    return (
                      <div
                        key={output.agent_name}
                        className="space-y-1.5 animate-slideUpIn"
                        style={{ animationDelay: `${oIdx * 80}ms` }}
                      >
                        <AgentCard response={output} />
                        {/* Tool activity inline under each agent card */}
                        {agentTools.map((tc, ti) => (
                          <div
                            key={ti}
                            className="text-xs bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2 flex items-start gap-2"
                          >
                            <Wrench className="w-3.5 h-3.5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" aria-hidden="true" />
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

              {/* Critiques */}
              {round.critiques.length > 0 && (
                <div className="px-4 pb-4 space-y-2">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                    Critiques ({round.critiques.length})
                  </p>
                  <div className="space-y-2">
                    {round.critiques.slice(0, 6).map((c, i) => (
                      <div key={i} className="animate-slideUpIn" style={{ animationDelay: `${i * 60}ms` }}>
                        <CritiqueView critiques={[c]} />
                      </div>
                    ))}
                    {round.critiques.length > 6 && (
                      <p className="text-xs text-gray-400">
                        +{round.critiques.length - 6} more critiques
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Moderator synthesis — quote-style block */}
              {synthesis && (
                <div className="px-4 pb-4 animate-slideUpIn">
                  <div className="relative rounded-lg bg-surface ring-1 ring-black/5 dark:ring-white/10 p-3 pl-4 text-sm overflow-hidden">
                    <span
                      aria-hidden="true"
                      className="absolute left-0 top-0 bottom-0 w-1"
                      style={{ backgroundColor: agentColor("Moderator") }}
                    />
                    <p className="flex items-center gap-2 font-semibold text-gray-700 dark:text-gray-300 mb-1.5">
                      <AgentAvatar name="Moderator" size="sm" /> Moderator synthesis
                    </p>
                    <Markdown className="text-gray-700 dark:text-gray-300">{synthesis.summary}</Markdown>
                    {synthesis.agreement_areas.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {synthesis.agreement_areas.map((a, i) => (
                          <Badge key={i} tone="success">✓ {a}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Query banner + connection status */}
      {state.query && (
        <div className="bg-accent-50 dark:bg-accent-950/30 ring-1 ring-accent-200 dark:ring-accent-800 rounded-2xl p-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-accent-500 font-semibold uppercase tracking-wide mb-1">
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
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <CircleStop className="w-3 h-3" aria-hidden="true" />
                {cancelling ? "Stopping…" : "Stop debate"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Connection lost banner */}
      {maxReconnectsHit && (
        <div className="flex items-center justify-between p-3 rounded-lg bg-red-50 dark:bg-red-950/30 ring-1 ring-red-200 dark:ring-red-800 text-sm text-red-700 dark:text-red-400">
          <span>Connection lost after multiple retries.</span>
          <Button variant="danger" size="sm" onClick={startStream} className="ml-4">
            Reconnect
          </Button>
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
            <span className="font-medium flex items-center gap-2">
              Round {state.currentRound} of {state.maxRounds}
              {state.currentPhase ? (
                <Badge
                  tone={PHASE_META[state.currentPhase]?.tone ?? "info"}
                  className="capitalize"
                >
                  {state.currentPhase}
                </Badge>
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
              className="h-full bg-gradient-to-r from-accent-500 to-violet-500 rounded-full transition-all duration-700"
              style={{ width: `${Math.min((state.currentRound / state.maxRounds) * 100, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Agent presence strip (only during active streaming) */}
      {state.status === "streaming" && Object.keys(state.agentStatus).length > 0 && (
        <div className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {Object.entries(state.agentStatus).map(([name, st]) => (
              <span key={name} className="inline-flex items-center gap-2" title={`${name}: ${st}`}>
                <AgentAvatar
                  name={name}
                  size="md"
                  status={st === "working" ? "working" : st === "done" ? "done" : st === "timeout" ? "timeout" : "idle"}
                />
                <span className="flex flex-col leading-tight">
                  <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{name}</span>
                  <span
                    className={`text-[10px] ${
                      st === "working"
                        ? "text-accent-600 dark:text-accent-400"
                        : st === "done"
                        ? "text-green-600 dark:text-green-400"
                        : st === "timeout"
                        ? "text-amber-600 dark:text-amber-400"
                        : "text-gray-400"
                    }`}
                  >
                    {st === "working" ? "thinking…" : st === "done" ? "done" : st === "timeout" ? "timed out" : "waiting"}
                  </span>
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Answer-first: decision + collapsible transcript once the debate is done */}
      {isDone && state.finalDecision && (
        <div className="space-y-4">
          <ResultBanner decision={state.finalDecision} />
          <FinalDecisionPanel decision={state.finalDecision} />
          {state.rounds.length > 0 && (
            <div className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card overflow-hidden">
              <CollapsibleSection
                headerClassName="px-4 py-3 text-sm font-semibold text-gray-700 dark:text-gray-200 hover:bg-surface transition-colors"
                bodyClassName="px-4 pb-4"
                title={
                  <span className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-accent-500" aria-hidden="true" />
                    Agent Confidence Drift
                  </span>
                }
              >
                <ConfidenceDriftChart rounds={state.rounds} />
              </CollapsibleSection>
            </div>
          )}
        </div>
      )}
      {isDone && (
        <CollapsibleSection
          open={showTranscript}
          onToggle={setShowTranscript}
          headerClassName="py-3 border-t border-line text-sm font-semibold text-gray-600 dark:text-gray-300 hover:text-gray-800 dark:hover:text-gray-100 transition-colors"
          bodyClassName="pt-2"
          title={
            <span className="flex items-center gap-2">
              <FileText className="w-4 h-4" aria-hidden="true" />
              Debate transcript
              <span className="text-xs font-normal text-gray-400">
                {state.rounds.length} round{state.rounds.length !== 1 ? "s" : ""} · {totalCritiques} critique{totalCritiques !== 1 ? "s" : ""}
              </span>
            </span>
          }
        >
          {renderRounds}
        </CollapsibleSection>
      )}

      {/* Live rounds — shown along the timeline while streaming */}
      {!isDone && renderRounds}

      {/* Streaming spinner */}
      {state.status === "streaming" && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
          <Loader2 className="w-4 h-4 text-accent-400 animate-spin" aria-hidden="true" />
          Agents deliberating…
        </div>
      )}

      {/* Keyboard hint */}
      {(!isDone || showTranscript) && state.rounds.length > 1 && (
        <p className="text-center text-xs text-gray-400 dark:text-gray-500 mt-2">
          Press <kbd className="px-1 py-0.5 rounded border border-line-strong font-mono text-xs">J</kbd> / <kbd className="px-1 py-0.5 rounded border border-line-strong font-mono text-xs">K</kbd> to navigate between rounds
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
