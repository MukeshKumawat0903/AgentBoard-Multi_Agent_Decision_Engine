/**
 * Simulate page – run N independent parallel debates for the same query
 * and compare stability across runs.
 */

"use client";

import { useState, useEffect, useRef } from "react";
import { cancelSimulationJob, getDebateModes, getSimulationJob, startSimulation } from "@/lib/api";
import type { SimulationJob, SimulationResult } from "@/lib/types";

/** How often to poll a running simulation job (ms). */
const POLL_INTERVAL_MS = 2_000;

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
  // null: use the selected mode's preset (quick 2 · standard 2 · thorough 6)
  const [maxRounds, setMaxRounds] = useState<number | null>(null);
  // Server default (DEFAULT_DEBATE_MODE) once loaded, unless the user already chose; Quick until then.
  const [mode, setMode] = useState("quick");
  const modeChosen = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  // Running job id, so it can be cancelled (and polling stopped) on demand or unmount.
  const jobIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Don't leave 2–5 debates burning tokens after the user has left the page.
      if (jobIdRef.current) cancelSimulationJob(jobIdRef.current).catch(() => {});
    };
  }, []);

  useEffect(() => {
    getDebateModes()
      .then((m) => {
        if (mountedRef.current && !modeChosen.current) setMode(m.default_mode);
      })
      .catch(() => {});
  }, []);

  // Pre-fill query from URL ?query= param (e.g. navigated from compare page)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("query");
    if (q) setQuery(q);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim().length < 10) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      // Runs as a background job: a single long request would outlive proxy timeouts.
      let job: SimulationJob = await startSimulation({
        query: query.trim(),
        runs,
        mode,
        ...(maxRounds ? { max_rounds: maxRounds } : {}),
      });
      jobIdRef.current = job.job_id;
      while (job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        if (!mountedRef.current) return;
        job = await getSimulationJob(job.job_id);
      }
      if (!mountedRef.current) return;
      if (job.status === "completed" && job.result) setResult(job.result);
      else if (job.status === "cancelled") setError("Simulation cancelled.");
      else setError(job.error ?? "Simulation failed.");
    } catch (err) {
      if (mountedRef.current) setError(err instanceof Error ? err.message : "Simulation failed.");
    } finally {
      jobIdRef.current = null;
      if (mountedRef.current) setLoading(false);
    }
  }

  function handleCancel() {
    if (jobIdRef.current) cancelSimulationJob(jobIdRef.current).catch(() => {});
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8 animate-fadeIn">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-gray-800 dark:text-gray-100 mb-1">Scenario Simulation</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Run N independent debates in parallel and compare their consistency and stability.
        </p>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-6 space-y-5">
        <div>
          <label htmlFor="sim-query" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Decision query
          </label>
          <textarea
            id="sim-query"
            rows={3}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
            placeholder="e.g. Should we migrate our monolith to microservices?"
            className="w-full rounded-lg border border-line-strong px-4 py-3 text-sm
                       bg-surface-raised text-gray-900 dark:text-gray-100
                       placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-accent-500
                       disabled:opacity-60 resize-y"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label htmlFor="sim-runs" className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Runs (2–5)
            </label>
            <input
              id="sim-runs"
              type="number"
              min={2}
              max={5}
              value={runs}
              onChange={(e) => setRuns(Number(e.target.value))}
              disabled={loading}
              className="w-full rounded-lg border border-line-strong px-3 py-2 text-sm
                         bg-surface-raised text-gray-900 dark:text-gray-100
                         focus:outline-none focus:ring-2 focus:ring-accent-500 disabled:opacity-60"
            />
          </div>
          <div>
            <label htmlFor="sim-max-rounds" className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Max rounds
            </label>
            <input
              id="sim-max-rounds"
              type="number"
              min={2}
              max={6}
              value={maxRounds ?? ""}
              placeholder="Mode default"
              onChange={(e) => setMaxRounds(e.target.value ? Number(e.target.value) : null)}
              disabled={loading}
              className="w-full rounded-lg border border-line-strong px-3 py-2 text-sm
                         bg-surface-raised text-gray-900 dark:text-gray-100
                         focus:outline-none focus:ring-2 focus:ring-accent-500 disabled:opacity-60"
            />
          </div>
          <div>
            <label htmlFor="sim-mode" className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Mode
            </label>
            <select
              id="sim-mode"
              value={mode}
              onChange={(e) => {
                modeChosen.current = true;
                setMode(e.target.value);
              }}
              disabled={loading}
              className="w-full rounded-lg border border-line-strong px-3 py-2 text-sm
                         bg-surface-raised text-gray-900 dark:text-gray-100
                         focus:outline-none focus:ring-2 focus:ring-accent-500 disabled:opacity-60"
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
          className="w-full py-3 rounded-lg bg-accent-600 text-white font-semibold text-sm
                     hover:bg-accent-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Running {runs} parallel debates…
            </span>
          ) : `Run ${runs} Simulations`}
        </button>
        {loading && (
          <button
            type="button"
            onClick={handleCancel}
            className="w-full py-2 rounded-lg text-sm text-gray-600 dark:text-gray-300 ring-1 ring-line-strong hover:bg-surface transition"
          >
            Cancel simulation
          </button>
        )}

        {error && (
          <p className="text-xs text-red-500 text-center">{error}</p>
        )}
      </form>

      {/* Results */}
      {result && (
        <div className="space-y-6">
          {/* Stability overview */}
          <div className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-gray-800 dark:text-gray-100">Stability Overview</h2>
              <span className={`px-3 py-1 rounded-full text-sm font-bold ${RATING_COLOR[result.stability_rating] ?? ""}`}>
                {result.stability_rating} Stability
              </span>
            </div>

            {/* NB4: warn when some runs failed */}
            {result.runs_completed < result.runs && (
              <div className="mb-3 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-xs text-amber-700 dark:text-amber-400">
                ⚠ {result.runs_completed} of {result.runs} runs completed — {result.runs - result.runs_completed} run{result.runs - result.runs_completed !== 1 ? "s" : ""} failed.
              </div>
            )}

            <div className="space-y-3 mb-4">
              {/* FI6: explanatory tooltip on each score label */}
              <ScoreBar label="Consistency Score" value={result.consistency_score} />
              <p className="text-xs text-gray-400 -mt-1 pl-0.5">
                Higher = agents reach the same decision regardless of LLM sampling variation.
              </p>
              <ScoreBar label="Avg Agreement Score" value={result.avg_agreement_score} />
              <p className="text-xs text-gray-400 -mt-1 pl-0.5">
                Mean consensus level reached across all runs (0 = no consensus, 1 = full agreement).
              </p>
            </div>

            <p className="text-xs text-gray-400">
              Confidence variance: <span className="font-medium tabular-nums">{result.confidence_variance.toFixed(3)}</span>
              {" · "}
              {/* NB4: show actual/requested count */}
              {result.runs_completed === result.runs
                ? `${result.runs} independent runs`
                : `${result.runs_completed}/${result.runs} runs completed`}
            </p>
          </div>

          {/* Stable risk flags */}
          {result.stable_risk_flags.length > 0 && (
            <div className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-6">
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
              Individual Runs ({result.runs_completed}{result.runs_completed < result.runs ? `/${result.runs}` : ""})
            </h3>
            <div className="space-y-3">
              {result.decisions.map((decision, i) => (
                <div
                  key={i}
                  className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-semibold text-accent-600 dark:text-accent-400">
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
