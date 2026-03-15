"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { FinalDecision, HistoryItem } from "@/lib/types";
import { getHistoryItem, getHistory, ApiError } from "@/lib/api";
import ConfidenceMeter from "@/components/ConfidenceMeter";

export default function CompareContent() {
  const router = useRouter();

  const [inputA, setInputA] = useState("");
  const [inputB, setInputB] = useState("");
  const [debateA, setDebateA] = useState<FinalDecision | null>(null);
  const [debateB, setDebateB] = useState<FinalDecision | null>(null);
  const [errorA, setErrorA] = useState<string | null>(null);
  const [errorB, setErrorB] = useState<string | null>(null);
  const [loadingA, setLoadingA] = useState(false);
  const [loadingB, setLoadingB] = useState(false);
  const [recentItems, setRecentItems] = useState<HistoryItem[]>([]);

  useEffect(() => {
    getHistory({ limit: 8 })
      .then((r) => setRecentItems(r.items))
      .catch(() => {});
  }, []);

  const loadDebate = useCallback(
    async (
      threadId: string,
      setDebate: (d: FinalDecision | null) => void,
      setError: (e: string | null) => void,
      setLoading: (l: boolean) => void,
    ) => {
      if (!threadId.trim()) return;
      setLoading(true);
      setError(null);
      try {
        const d = await getHistoryItem(threadId.trim());
        setDebate(d);
      } catch (err) {
        setDebate(null);
        setError(
          err instanceof ApiError && err.status === 404
            ? "Debate not found."
            : err instanceof Error
            ? err.message
            : "Failed to load debate.",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // On mount, read URL search params and auto-load
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const a = params.get("a") ?? "";
    const b = params.get("b") ?? "";
    if (a) setInputA(a);
    if (b) setInputB(b);
    if (a) loadDebate(a, setDebateA, setErrorA, setLoadingA);
    if (b) loadDebate(b, setDebateB, setErrorB, setLoadingB);
  }, [loadDebate]);

  function applyAndLoad() {
    const params = new URLSearchParams();
    if (inputA) params.set("a", inputA);
    if (inputB) params.set("b", inputB);
    router.push(`/compare?${params.toString()}`);
    if (inputA) loadDebate(inputA, setDebateA, setErrorA, setLoadingA);
    if (inputB) loadDebate(inputB, setDebateB, setErrorB, setLoadingB);
  }

  function pickRecent(item: HistoryItem, slot: "a" | "b") {
    if (slot === "a") {
      setInputA(item.thread_id);
    } else {
      setInputB(item.thread_id);
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">
          Compare Debates
        </h1>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
          Select two debate thread IDs to compare their decisions side by side.
        </p>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-5 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Debate A
            </label>
            <input
              type="text"
              value={inputA}
              onChange={(e) => setInputA(e.target.value)}
              placeholder="Enter thread ID…"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Debate B
            </label>
            <input
              type="text"
              value={inputB}
              onChange={(e) => setInputB(e.target.value)}
              placeholder="Enter thread ID…"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <button
          onClick={applyAndLoad}
          disabled={!inputA && !inputB}
          className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-40 transition"
        >
          Compare
        </button>

        {recentItems.length > 0 && (
          <div>
            <p className="text-xs text-gray-400 mb-2">Recent debates (click to fill a slot):</p>
            <div className="flex flex-wrap gap-2">
              {recentItems.map((item) => (
                <div key={item.thread_id} className="flex gap-1">
                  <button
                    onClick={() => pickRecent(item, "a")}
                    className="px-2 py-1 rounded border border-gray-300 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition truncate max-w-[160px]"
                    title={item.user_query}
                  >
                    A: {item.user_query.slice(0, 24)}…
                  </button>
                  <button
                    onClick={() => pickRecent(item, "b")}
                    className="px-2 py-1 rounded border border-gray-300 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition truncate max-w-[90px]"
                    title={item.user_query}
                  >
                    B
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {(debateA || debateB || loadingA || loadingB || errorA || errorB) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DebateColumn
            label="Debate A"
            debate={debateA}
            loading={loadingA}
            error={errorA}
            otherDebate={debateB}
          />
          <DebateColumn
            label="Debate B"
            debate={debateB}
            loading={loadingB}
            error={errorB}
            otherDebate={debateA}
          />
        </div>
      )}
    </div>
  );
}

function DebateColumn({
  label,
  debate,
  loading,
  error,
  otherDebate,
}: {
  label: string;
  debate: FinalDecision | null;
  loading: boolean;
  error: string | null;
  otherDebate: FinalDecision | null;
}) {
  return (
    <div className="space-y-4">
      <h2 className="font-semibold text-gray-700 dark:text-gray-300 text-sm uppercase tracking-wide">
        {label}
      </h2>

      {loading && (
        <div className="flex justify-center py-10">
          <div className="w-6 h-6 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {error && (
        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {debate && (
        <div className="space-y-4">
          {debate.query && (
            <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
              <p className="text-xs text-blue-500 font-semibold mb-1">Query</p>
              <p className="text-gray-800 dark:text-gray-200 text-sm">{debate.query}</p>
            </div>
          )}

          <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-4">
            <p className="text-xs text-gray-400 font-semibold mb-1">Decision</p>
            <p className="text-gray-800 dark:text-gray-200 leading-relaxed">{debate.decision}</p>
          </div>

          <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-4 grid grid-cols-2 gap-4">
            <ConfidenceMeter score={debate.confidence_score} label="Confidence" />
            <ConfidenceMeter score={debate.agreement_score} label="Agreement" />
          </div>

          <div className="flex flex-wrap gap-2 text-xs">
            <MetaBadge
              value={`${debate.total_rounds} round${debate.total_rounds > 1 ? "s" : ""}`}
              highlight={
                otherDebate
                  ? debate.total_rounds < otherDebate.total_rounds
                    ? "better"
                    : debate.total_rounds > otherDebate.total_rounds
                    ? "worse"
                    : "equal"
                  : "neutral"
              }
            />
            <MetaBadge
              value={debate.termination_reason.replace(/_/g, " ")}
              highlight={
                debate.termination_reason === "consensus_reached" ? "better" : "neutral"
              }
            />
            <MetaBadge
              value={`${Math.round(debate.confidence_score * 100)}% confidence`}
              highlight={
                otherDebate
                  ? debate.confidence_score > otherDebate.confidence_score
                    ? "better"
                    : debate.confidence_score < otherDebate.confidence_score
                    ? "worse"
                    : "equal"
                  : "neutral"
              }
            />
          </div>

          <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-4">
            <p className="text-xs text-gray-400 font-semibold mb-1">Rationale</p>
            <p className="text-gray-600 dark:text-gray-400 text-sm leading-relaxed">
              {debate.rationale_summary}
            </p>
          </div>

          {debate.risk_flags.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-4">
              <p className="text-xs text-gray-400 font-semibold mb-2">
                Risk Flags ({debate.risk_flags.length})
              </p>
              <div className="flex flex-wrap gap-1">
                {debate.risk_flags.map((flag, i) => {
                  const isOnlyHere =
                    otherDebate && !otherDebate.risk_flags.includes(flag);
                  return (
                    <span
                      key={i}
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        isOnlyHere
                          ? "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400 ring-1 ring-orange-400"
                          : "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
                      }`}
                      title={isOnlyHere ? "Unique to this debate" : undefined}
                    >
                      {flag}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {debate.alternatives.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-4">
              <p className="text-xs text-gray-400 font-semibold mb-2">Alternatives</p>
              <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-400 space-y-1">
                {debate.alternatives.map((alt, i) => (
                  <li key={i}>{alt}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MetaBadge({
  value,
  highlight,
}: {
  value: string;
  highlight: "better" | "worse" | "equal" | "neutral";
}) {
  const classes = {
    better: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400",
    worse: "bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400",
    equal: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300",
    neutral: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300",
  }[highlight];

  return (
    <span className={`px-2 py-0.5 rounded-full font-medium ${classes}`}>
      {value}
    </span>
  );
}
