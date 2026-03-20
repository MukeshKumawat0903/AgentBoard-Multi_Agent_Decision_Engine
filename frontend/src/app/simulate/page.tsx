/**
 * Simulate page – run N independent parallel debates for the same query
 * and compare stability across runs.
 */

"use client";

import { useState } from "react";
import { runSimulation } from "@/lib/api";
import type { SimulationResult } from "@/lib/types";

const RATING_COLOR: Record<string, string> = {
  High: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  Medium: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300",
  Low: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 55 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400">
        <span>{label}</span>
        <span className="tabular-nums font-medium">{pct}%</span>
      </div>
      <div className="h-1.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function SimulatePage() {
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState(3);
  const [maxRounds, setMaxRounds] = useState(3);
  const [mode, setMode] = useState("standard");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim().length < 10) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runSimulation({ query: query.trim(), runs, max_rounds: maxRounds, mode });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-1">Scenario Simulation</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Run N independent debates in parallel and compare their consistency and stability.
        </p>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Decision query
          </label>
          <textarea
            rows={3}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
            placeholder="e.g. Should we migrate our monolith to microservices?"
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-3 text-sm
                       bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                       placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500
                       disabled:opacity-60 resize-y"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Runs (2–5)
            </label>
            <input
              type="number"
              min={2}
              max={5}
              value={runs}
              onChange={(e) => setRuns(Number(e.target.value))}
              disabled={loading}
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm
                         bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                         focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Max rounds
            </label>
            <input
              type="number"
              min={2}
              max={6}
              value={maxRounds}
              onChange={(e) => setMaxRounds(Number(e.target.value))}
              disabled={loading}
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm
                         bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                         focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Mode
            </label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              disabled={loading}
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm
                         bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                         focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
            >
              <option value="quick">Quick</option>
              <option value="standard">Standard</option>
              <option value="thorough">Thorough</option>
            </select>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || query.trim().length < 10}
          className="w-full py-3 rounded-lg bg-blue-600 text-white font-semibold text-sm
                     hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Running {runs} parallel debates…
            </span>
          ) : `Run ${runs} Simulations`}
        </button>

        {error && (
          <p className="text-xs text-red-500 text-center">{error}</p>
        )}
      </form>

      {/* Results */}
      {result && (
        <div className="space-y-6">
          {/* Stability overview */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-gray-800 dark:text-gray-100">Stability Overview</h2>
              <span className={`px-3 py-1 rounded-full text-sm font-bold ${RATING_COLOR[result.stability_rating] ?? ""}`}>
                {result.stability_rating} Stability
              </span>
            </div>

            <div className="space-y-3 mb-4">
              <ScoreBar label="Consistency Score" value={result.consistency_score} />
              <ScoreBar label="Avg Agreement Score" value={result.avg_agreement_score} />
            </div>

            <p className="text-xs text-gray-400">
              Confidence variance: <span className="font-medium tabular-nums">{result.confidence_variance.toFixed(3)}</span>
              {" · "}{result.runs} independent runs
            </p>
          </div>

          {/* Stable risk flags */}
          {result.stable_risk_flags.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
              <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">
                Stable Risk Flags <span className="text-xs text-gray-400">(appear in ≥70% of runs)</span>
              </h3>
              <div className="flex flex-wrap gap-2">
                {result.stable_risk_flags.map((flag, i) => (
                  <span
                    key={i}
                    className="px-3 py-1 rounded-full bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 text-sm font-medium"
                  >
                    {flag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Per-run decisions */}
          <div>
            <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">
              Individual Runs ({result.runs})
            </h3>
            <div className="space-y-3">
              {result.decisions.map((decision, i) => (
                <div
                  key={i}
                  className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">
                      Run {i + 1}
                    </span>
                    <span className="text-xs text-gray-400 tabular-nums">
                      Agreement {Math.round((decision.agreement_score ?? 0) * 100)}%
                    </span>
                    <span className="text-xs text-gray-400 tabular-nums">
                      Confidence {Math.round((decision.confidence_score ?? 0) * 100)}%
                    </span>
                  </div>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{decision.decision}</p>
                  {(decision.risk_flags ?? []).length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {decision.risk_flags.map((f, j) => (
                        <span
                          key={j}
                          className="px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-xs"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
