/**
 * Analytics & Evaluation page — Phase 5.2
 * Route: /analytics
 *
 * Sections
 * --------
 * 1. KPI row          – total debates, avg rounds, avg agreement, consensus rate
 * 2. Debate trend     – LineChart of debates per day (last 30 days)
 * 3. Termination      – PieChart of converged vs max-rounds
 * 4. Convergence curve– LineChart of avg agreement score by round
 * 5. Agent confidence – BarChart of avg confidence per agent
 * 6. Agreement matrix – coloured grid of pairwise agent agreement
 * 7. Quality tab      – quality scores by template / mode / domain pack
 */

"use client";

import { useEffect, useState, useCallback } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  getAnalyticsOverview,
  getAnalyticsAgents,
  getAnalyticsConvergence,
  getAnalyticsQuality,
  ApiError,
} from "@/lib/api";
import type {
  AnalyticsOverview,
  AnalyticsAgents,
  AnalyticsConvergence,
  AnalyticsQuality,
} from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const PIE_COLORS = ["#3B82F6", "#EF4444", "#22C55E", "#A855F7", "#EAB308", "#F97316"];

const AGENT_COLORS: Record<string, string> = {
  Analyst: "#3B82F6",
  Risk: "#EF4444",
  Strategy: "#22C55E",
  Ethics: "#A855F7",
  Moderator: "#EAB308",
};

function agentColor(name: string) {
  return AGENT_COLORS[name] ?? "#6B7280";
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

function heatColor(v: number): string {
  // 0 → cool blue, 1 → warm green
  const r = Math.round(59 + (34 - 59) * v);
  const g = Math.round(130 + (197 - 130) * v);
  const b = Math.round(246 + (94 - 246) * v);
  return `rgb(${r},${g},${b})`;
}

/* ------------------------------------------------------------------ */
/* KPI Card                                                            */
/* ------------------------------------------------------------------ */
function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 flex flex-col gap-1">
      <div className="text-xs text-gray-400 dark:text-gray-500 font-medium uppercase tracking-wide">
        {label}
      </div>
      <div className="text-2xl font-bold text-gray-800 dark:text-gray-100">{value}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Section wrapper                                                     */
/* ------------------------------------------------------------------ */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
      <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-4">{title}</h2>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Agreement matrix                                                    */
/* ------------------------------------------------------------------ */
function AgreementMatrix({ matrix }: { matrix: Record<string, Record<string, number>> }) {
  const agents = Object.keys(matrix);
  if (agents.length === 0)
    return <p className="text-sm text-gray-400">No agent data yet.</p>;

  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>
            <th className="p-2 text-gray-400" />
            {agents.map((a) => (
              <th
                key={a}
                className="p-2 text-gray-500 dark:text-gray-400 font-medium text-center"
              >
                {a}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {agents.map((row) => (
            <tr key={row}>
              <td className="p-2 text-gray-500 dark:text-gray-400 font-medium pr-4">{row}</td>
              {agents.map((col) => {
                const v = matrix[row]?.[col] ?? 0;
                return (
                  <td
                    key={col}
                    className="p-2 text-center rounded"
                    style={{ backgroundColor: heatColor(v), color: "#fff", minWidth: 48 }}
                    title={`${row} ↔ ${col}: ${pct(v)}`}
                  >
                    {pct(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Quality tab content                                                 */
/* ------------------------------------------------------------------ */
function QualityPanel({ quality }: { quality: AnalyticsQuality | null }) {
  if (!quality)
    return (
      <div className="flex justify-center py-8">
        <div className="w-5 h-5 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );

  if (quality.evaluated_count === 0)
    return (
      <p className="text-sm text-gray-400 py-4">
        No evaluations yet. Run{" "}
        <span className="font-mono">POST /decision/&#123;id&#125;/evaluate</span> on completed
        debates to populate quality scores.
      </p>
    );

  const modeData = Object.entries(quality.scores_by_mode).map(([k, v]) => ({
    name: k,
    score: v,
  }));
  const domainData = Object.entries(quality.scores_by_domain_pack).map(([k, v]) => ({
    name: k,
    score: v,
  }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <KpiCard
          label="Evaluated decisions"
          value={quality.evaluated_count}
        />
        <KpiCard
          label="Avg quality score"
          value={quality.avg_quality_score !== null ? quality.avg_quality_score.toFixed(3) : "—"}
          sub="0–1 scale"
        />
      </div>

      {modeData.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
            Quality by mode
          </h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={modeData} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#9CA3AF" }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#9CA3AF" }} />
              <Tooltip
                formatter={(v) => typeof v === 'number' ? v.toFixed(3) : ''}
                contentStyle={{ backgroundColor: "#1F2937", border: "none", borderRadius: 8 }}
                labelStyle={{ color: "#F3F4F6" }}
              />
              <Bar dataKey="score" fill="#3B82F6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {domainData.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
            Quality by domain pack
          </h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={domainData} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#9CA3AF" }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#9CA3AF" }} />
              <Tooltip
                formatter={(v) => typeof v === 'number' ? v.toFixed(3) : ''}
                contentStyle={{ backgroundColor: "#1F2937", border: "none", borderRadius: 8 }}
                labelStyle={{ color: "#F3F4F6" }}
              />
              <Bar dataKey="score" fill="#22C55E" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {quality.best_performing_templates.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <h3 className="text-sm font-medium text-green-600 dark:text-green-400 mb-2">
              Best templates
            </h3>
            <ul className="space-y-1">
              {quality.best_performing_templates.map((t) => (
                <li key={t} className="text-sm text-gray-600 dark:text-gray-300 flex items-center gap-2">
                  <span className="text-green-500">▲</span> {t}
                  {quality.scores_by_template[t] !== undefined && (
                    <span className="ml-auto text-xs text-gray-400">
                      {quality.scores_by_template[t].toFixed(3)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-medium text-red-600 dark:text-red-400 mb-2">
              Worst templates
            </h3>
            <ul className="space-y-1">
              {quality.worst_performing_templates.map((t) => (
                <li key={t} className="text-sm text-gray-600 dark:text-gray-300 flex items-center gap-2">
                  <span className="text-red-500">▼</span> {t}
                  {quality.scores_by_template[t] !== undefined && (
                    <span className="ml-auto text-xs text-gray-400">
                      {quality.scores_by_template[t].toFixed(3)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main page                                                           */
/* ------------------------------------------------------------------ */

type Tab = "overview" | "agents" | "quality";

export default function AnalyticsPage() {
  const [tab, setTab] = useState<Tab>("overview");

  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [agents, setAgents] = useState<AnalyticsAgents | null>(null);
  const [convergence, setConvergence] = useState<AnalyticsConvergence | null>(null);
  const [quality, setQuality] = useState<AnalyticsQuality | null>(null);

  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [loadingConvergence, setLoadingConvergence] = useState(true);
  const [loadingQuality, setLoadingQuality] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const loadOverviewAndConvergence = useCallback(async () => {
    try {
      const [ov, cv] = await Promise.all([
        getAnalyticsOverview(),
        getAnalyticsConvergence(),
      ]);
      setOverview(ov);
      setConvergence(cv);
    } catch (e) {
      setError(e instanceof ApiError ? `API ${e.status}` : "Failed to load analytics.");
    } finally {
      setLoadingOverview(false);
      setLoadingConvergence(false);
    }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      setAgents(await getAnalyticsAgents());
    } catch {
      // non-fatal; agents panel will show empty
    } finally {
      setLoadingAgents(false);
    }
  }, []);

  const loadQuality = useCallback(async () => {
    if (quality !== null) return;
    setLoadingQuality(true);
    try {
      setQuality(await getAnalyticsQuality());
    } catch {
      setQuality({
        evaluated_count: 0,
        avg_quality_score: null,
        scores_by_template: {},
        scores_by_mode: {},
        scores_by_domain_pack: {},
        best_performing_templates: [],
        worst_performing_templates: [],
      });
    } finally {
      setLoadingQuality(false);
    }
  }, [quality]);

  useEffect(() => {
    loadOverviewAndConvergence();
    loadAgents();
  }, [loadOverviewAndConvergence, loadAgents]);

  useEffect(() => {
    if (tab === "quality") loadQuality();
  }, [tab, loadQuality]);

  // ---------- derived data --------------------------------
  const trendData =
    overview?.debates_per_day.map((d) => ({ date: d.date.slice(5), count: d.count })) ?? [];

  const terminationData = Object.entries(overview?.debates_by_termination ?? {}).map(
    ([name, value]) => ({
      name: name.replace(/_/g, " "),
      value,
    }),
  );

  const convergenceCurve = (convergence?.avg_agreement_by_round ?? []).map((v, i) => ({
    round: i + 1,
    agreement: v,
  }));

  const agentBarData = Object.entries(agents?.agents ?? {}).map(([name, stats]) => ({
    name,
    confidence: stats.avg_confidence,
    contribution: stats.avg_contribution_score,
  }));

  const consensusRate =
    overview && overview.total_debates > 0
      ? (
          ((overview.debates_by_termination["consensus_reached"] ?? 0) /
            overview.total_debates) *
          100
        ).toFixed(1) + "%"
      : "—";

  // ---------- loading / error --------------------------------
  const isLoading = loadingOverview;

  if (isLoading)
    return (
      <div className="flex justify-center py-24">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );

  if (error)
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      </div>
    );

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">
          Analytics &amp; Evaluation
        </h1>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
          Data-driven insights into debate behaviour, agent performance, and decision quality.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700">
        {(["overview", "agents", "quality"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize transition border-b-2 -mb-px ${
              tab === t
                ? "border-blue-600 text-blue-600 dark:text-blue-400"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            }`}
          >
            {t === "overview" ? "Overview" : t === "agents" ? "Agents" : "Quality"}
          </button>
        ))}
      </div>

      {/* ---- OVERVIEW TAB ---- */}
      {tab === "overview" && (
        <div className="space-y-6">
          {/* KPI row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <KpiCard
              label="Total debates"
              value={overview?.total_debates ?? 0}
            />
            <KpiCard
              label="Avg rounds"
              value={overview?.avg_rounds_to_consensus.toFixed(1) ?? "—"}
              sub="to completion"
            />
            <KpiCard
              label="Avg agreement"
              value={overview ? pct(overview.avg_agreement_score) : "—"}
              sub="final score"
            />
            <KpiCard
              label="Consensus rate"
              value={consensusRate}
              sub="converged debates"
            />
          </div>

          {/* Debate trend */}
          <Section title="Debates per day (last 30 days)">
            {trendData.length === 0 ? (
              <p className="text-sm text-gray-400">No debate data in the last 30 days.</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trendData} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9CA3AF" }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#9CA3AF" }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1F2937",
                      border: "none",
                      borderRadius: 8,
                    }}
                    labelStyle={{ color: "#F3F4F6" }}
                  />
                  <Line
                    type="monotone"
                    dataKey="count"
                    stroke="#3B82F6"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "#3B82F6" }}
                    activeDot={{ r: 5 }}
                    name="Debates"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Section>

          {/* Two-col: termination breakdown + convergence curve */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {/* Termination pie */}
            <Section title="Termination breakdown">
              {terminationData.length === 0 ? (
                <p className="text-sm text-gray-400">No completed debates yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={terminationData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={3}
                      dataKey="value"
                      nameKey="name"
                      label={({ name, percent }) =>
                        `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
                      }
                      labelLine={false}
                    >
                      {terminationData.map((_, idx) => (
                        <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1F2937",
                        border: "none",
                        borderRadius: 8,
                      }}
                      labelStyle={{ color: "#F3F4F6" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </Section>

            {/* Convergence curve */}
            <Section title="Avg agreement by round">
              {convergenceCurve.length === 0 ? (
                <p className="text-sm text-gray-400">No synthesis events recorded yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart
                    data={convergenceCurve}
                    margin={{ top: 4, right: 16, left: -10, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                    <XAxis
                      dataKey="round"
                      tick={{ fontSize: 11, fill: "#9CA3AF" }}
                      label={{
                        value: "Round",
                        position: "insideBottom",
                        offset: -2,
                        fill: "#9CA3AF",
                        fontSize: 10,
                      }}
                    />
                    <YAxis
                      domain={[0, 1]}
                      tick={{ fontSize: 11, fill: "#9CA3AF" }}
                      tickFormatter={(v) => pct(v)}
                    />
                    <Tooltip
                      formatter={(v) => pct(typeof v === 'number' ? v : 0)}
                      contentStyle={{
                        backgroundColor: "#1F2937",
                        border: "none",
                        borderRadius: 8,
                      }}
                      labelStyle={{ color: "#F3F4F6" }}
                    />
                    <Line
                      type="monotone"
                      dataKey="agreement"
                      stroke="#22C55E"
                      strokeWidth={2}
                      dot={{ r: 4, fill: "#22C55E" }}
                      activeDot={{ r: 6 }}
                      name="Agreement"
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Section>
          </div>

          {/* Mode + domain pack breakdowns */}
          {((convergence?.mode_breakdown &&
            Object.keys(convergence.mode_breakdown).length > 0) ||
            (convergence?.domain_pack_breakdown &&
              Object.keys(convergence.domain_pack_breakdown).length > 0)) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <Section title="Debates by mode">
                <ul className="space-y-2">
                  {Object.entries(convergence?.mode_breakdown ?? {}).map(([mode, count]) => (
                    <li key={mode} className="flex items-center gap-3 text-sm">
                      <span className="capitalize text-gray-600 dark:text-gray-300 w-20">
                        {mode}
                      </span>
                      <div className="flex-1 h-2 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full"
                          style={{
                            width: `${
                              (count /
                                Math.max(
                                  ...Object.values(convergence?.mode_breakdown ?? {}),
                                )) *
                              100
                            }%`,
                          }}
                        />
                      </div>
                      <span className="text-gray-400 text-xs w-6 text-right">{count}</span>
                    </li>
                  ))}
                </ul>
              </Section>
              <Section title="Debates by domain pack">
                <ul className="space-y-2">
                  {Object.entries(convergence?.domain_pack_breakdown ?? {}).map(
                    ([pack, count]) => (
                      <li key={pack} className="flex items-center gap-3 text-sm">
                        <span className="text-gray-600 dark:text-gray-300 w-24 truncate">
                          {pack}
                        </span>
                        <div className="flex-1 h-2 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                          <div
                            className="h-full bg-purple-500 rounded-full"
                            style={{
                              width: `${
                                (count /
                                  Math.max(
                                    ...Object.values(convergence?.domain_pack_breakdown ?? {}),
                                  )) *
                                100
                              }%`,
                            }}
                          />
                        </div>
                        <span className="text-gray-400 text-xs w-6 text-right">{count}</span>
                      </li>
                    ),
                  )}
                </ul>
              </Section>
            </div>
          )}
        </div>
      )}

      {/* ---- AGENTS TAB ---- */}
      {tab === "agents" && (
        <div className="space-y-6">
          {loadingAgents ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : agentBarData.length === 0 ? (
            <p className="text-sm text-gray-400 py-6">
              No agent data yet — run some debates first.
            </p>
          ) : (
            <>
              {/* Confidence + contribution chart */}
              <Section title="Agent confidence &amp; contribution">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart
                    data={agentBarData}
                    margin={{ top: 4, right: 16, left: -10, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#9CA3AF" }} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#9CA3AF" }} tickFormatter={(v) => pct(v)} />
                    <Tooltip
                      formatter={(v) => pct(typeof v === 'number' ? v : 0)}
                      contentStyle={{
                        backgroundColor: "#1F2937",
                        border: "none",
                        borderRadius: 8,
                      }}
                      labelStyle={{ color: "#F3F4F6" }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar
                      dataKey="confidence"
                      name="Avg confidence"
                      radius={[4, 4, 0, 0]}
                    >
                      {agentBarData.map((entry) => (
                        <Cell key={entry.name} fill={agentColor(entry.name)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </Section>

              {/* Agent stats cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {Object.entries(agents?.agents ?? {}).map(([name, stats]) => (
                  <div
                    key={name}
                    className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 space-y-3"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: agentColor(name) }}
                      />
                      <span className="font-semibold text-gray-800 dark:text-gray-100">
                        {name}
                      </span>
                    </div>
                    <div className="space-y-1 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-400">Avg confidence</span>
                        <span className="font-medium text-gray-700 dark:text-gray-200">
                          {pct(stats.avg_confidence)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Contribution score</span>
                        <span className="font-medium text-gray-700 dark:text-gray-200">
                          {stats.avg_contribution_score > 0
                            ? pct(stats.avg_contribution_score)
                            : "—"}
                        </span>
                      </div>
                      {Object.keys(stats.avg_critique_severity_given).length > 0 && (
                        <div className="pt-1">
                          <div className="text-gray-400 mb-1">Critique severity given</div>
                          <div className="flex gap-1 flex-wrap">
                            {Object.entries(stats.avg_critique_severity_given).map(
                              ([sev, cnt]) => (
                                <span
                                  key={sev}
                                  className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                                    sev === "critical"
                                      ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300"
                                      : sev === "high"
                                        ? "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300"
                                        : sev === "medium"
                                          ? "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300"
                                          : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
                                  }`}
                                >
                                  {sev} ({cnt})
                                </span>
                              ),
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* Agreement matrix */}
              {agents?.agreement_matrix &&
                Object.keys(agents.agreement_matrix).length > 0 && (
                  <Section title="Pairwise agreement matrix (fraction of debates both agents &gt; 70% confidence)">
                    <AgreementMatrix matrix={agents.agreement_matrix} />
                  </Section>
                )}
            </>
          )}
        </div>
      )}

      {/* ---- QUALITY TAB ---- */}
      {tab === "quality" && (
        <div className="space-y-6">
          <Section title="Decision quality scores">
            {loadingQuality ? (
              <div className="flex justify-center py-8">
                <div className="w-5 h-5 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : (
              <QualityPanel quality={quality} />
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
