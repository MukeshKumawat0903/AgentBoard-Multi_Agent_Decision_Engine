/**
 * FinalDecisionPanel – prominently displays the FinalDecision from a debate.
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import type { FinalDecision, EvaluationResult } from "@/lib/types";
import { evaluateDecision, exportDecision } from "@/lib/api";
import ConfidenceMeter from "./ConfidenceMeter";
import DebateTimeline from "./DebateTimeline";
import Markdown from "./Markdown";
import { useToast } from "./Toast";

interface FinalDecisionPanelProps {
  decision: FinalDecision;
}

/** Build a clean Markdown summary for clipboard / sharing. */
function buildMarkdownSummary(d: FinalDecision): string {
  const lines: string[] = ["# Decision", "", d.decision, "", "## Rationale", "", d.rationale_summary, ""];
  if (d.risk_flags.length) lines.push("## Risk Flags", "", ...d.risk_flags.map((f) => `- ${f}`), "");
  if (d.alternatives.length) lines.push("## Alternatives Considered", "", ...d.alternatives.map((a) => `- ${a}`), "");
  lines.push(
    "---",
    `Agreement ${Math.round(d.agreement_score * 100)}% · Confidence ${Math.round(
      d.confidence_score * 100,
    )}% · ${d.total_rounds} round${d.total_rounds > 1 ? "s" : ""} · ${d.termination_reason.replace(/_/g, " ")}`,
  );
  return lines.join("\n");
}

function useLocalBool(key: string, defaultValue = false): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState(defaultValue);
  useEffect(() => {
    const stored = localStorage.getItem(key);
    if (stored !== null) setValue(stored === "true");
  }, [key]);
  const set = useCallback((v: boolean) => {
    setValue(v);
    localStorage.setItem(key, String(v));
  }, [key]);
  return [value, set];
}

export default function FinalDecisionPanel({ decision }: FinalDecisionPanelProps) {
  const { showToast } = useToast();
  const [showTrace, setShowTrace] = useLocalBool("fdp:showTrace", false);
  const [showMinority, setShowMinority] = useLocalBool("fdp:showMinority", false);
  const [showDisagreements, setShowDisagreements] = useLocalBool("fdp:showDisagreements", false);
  const [showDissenting, setShowDissenting] = useLocalBool("fdp:showDissenting", false);
  const [exportLoading, setExportLoading] = useState<null | "markdown" | "pdf" | "json">(null);
  const [evalResult, setEvalResult] = useState<EvaluationResult | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);

  async function handleEvaluate() {
    setEvalLoading(true);
    setEvalError(null);
    try {
      const result = await evaluateDecision(decision.thread_id);
      setEvalResult(result);
    } catch (err) {
      setEvalError(err instanceof Error ? err.message : "Evaluation failed.");
    } finally {
      setEvalLoading(false);
    }
  }

  async function handleExport(format: "markdown" | "pdf") {
    setExportLoading(format);
    try {
      const blob = await exportDecision(decision.thread_id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `decision-${decision.thread_id}.${format === "pdf" ? "pdf" : "md"}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Export failed.", "error");
    } finally {
      setExportLoading(null);
    }
  }

  function handleDownloadJSON() {
    const blob = new Blob([JSON.stringify(decision, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `decision-${decision.thread_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Copy a Markdown summary of the decision to the clipboard.
  async function handleCopyDecision() {
    try {
      await navigator.clipboard.writeText(buildMarkdownSummary(decision));
      showToast("Decision copied to clipboard", "success");
    } catch {
      showToast("Could not copy to clipboard.", "error");
    }
  }

  // Copy a permalink to this debate.
  async function handleCopyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      showToast("Link copied to clipboard", "success");
    } catch {
      showToast("Could not copy link.", "error");
    }
  }

  const hasMinorityReport = (decision.minority_report?.length ?? 0) > 0;
  const hasKeyDisagreements = (decision.key_disagreements?.length ?? 0) > 0;
  const hasContributions = Object.keys(decision.agent_contribution_scores ?? {}).length > 0;

  return (
    <div className="space-y-6 pb-20">
      {/* Degraded-run warning: decision rested on fewer agents than expected */}
      {decision.degraded && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4">
          <span className="text-xl" aria-hidden="true">⚠️</span>
          <p className="text-sm text-amber-800 dark:text-amber-300 leading-relaxed">
            This decision was made with reduced input — the following agent
            {(decision.missing_agents?.length ?? 0) > 1 ? "s" : ""} did not contribute to the
            final round:{" "}
            <span className="font-semibold">{(decision.missing_agents ?? []).join(", ")}</span>.
            Treat it with extra caution.
          </p>
        </div>
      )}

      {/* Decision */}
      <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-2">Decision</h2>
        <Markdown className="text-lg text-gray-700 dark:text-gray-300">{decision.decision}</Markdown>
      </section>

      {/* Rationale */}
      <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
        <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2">Rationale</h3>
        <Markdown className="text-gray-600 dark:text-gray-400">{decision.rationale_summary}</Markdown>
      </section>

      {/* Scores */}
      <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6 grid grid-cols-1 sm:grid-cols-2 gap-6">
        <ConfidenceMeter score={decision.confidence_score} label="Confidence" />
        <ConfidenceMeter score={decision.agreement_score} label="Agreement" />
      </section>

      {/* Agent Contribution Scores */}
      {hasContributions && (
        <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">Agent Contributions</h3>
          <div className="space-y-2">
            {Object.entries(decision.agent_contribution_scores!).map(([agent, score]) => (
              <div key={agent} className="flex items-center gap-3">
                <span className="text-sm text-gray-600 dark:text-gray-400 w-20">{agent}</span>
                <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${Math.round(score * 100)}%` }}
                  />
                </div>
                <span className="text-xs text-gray-500 tabular-nums w-10 text-right">
                  {Math.round(score * 100)}%
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Meta badges */}
      <div className="flex flex-wrap gap-3 text-sm">
        <span className="px-3 py-1 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium">
          {decision.total_rounds} round{decision.total_rounds > 1 ? "s" : ""}
        </span>
        <span className="px-3 py-1 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 font-medium capitalize">
          {decision.termination_reason.replace(/_/g, " ")}
        </span>
        {decision.token_usage && decision.token_usage.total_tokens > 0 && (
          <span
            className="px-3 py-1 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 font-medium tabular-nums"
            title={`${decision.token_usage.input_tokens.toLocaleString()} in · ${decision.token_usage.output_tokens.toLocaleString()} out`}
          >
            🔢 {decision.token_usage.total_tokens.toLocaleString()} tokens
            {typeof decision.estimated_cost_usd === "number"
              ? ` · ~$${decision.estimated_cost_usd.toFixed(4)}`
              : ""}
          </span>
        )}
      </div>

      {/* Risk Flags */}
      {decision.risk_flags.length > 0 && (
        <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2">Risk Flags</h3>
          <div className="flex flex-wrap gap-2">
            {decision.risk_flags.map((flag, i) => (
              <span
                key={i}
                className="px-3 py-1 rounded-full bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 text-sm font-medium"
              >
                {flag}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Alternatives */}
      {decision.alternatives.length > 0 && (
        <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2">Alternatives Considered</h3>
          <ul className="list-disc list-inside text-gray-600 dark:text-gray-400 space-y-1">
            {decision.alternatives.map((alt, i) => (
              <li key={i}>{alt}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Dissenting Opinions */}
      {decision.dissenting_opinions.length > 0 && (
        <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <button
            onClick={() => setShowDissenting(!showDissenting)}
            className="w-full flex justify-between items-center"
          >
            <h3 className="font-semibold text-gray-700 dark:text-gray-300">
              Dissenting Opinions ({decision.dissenting_opinions.length})
            </h3>
            <span className="text-gray-400 text-sm">{showDissenting ? "▲" : "▼"}</span>
          </button>
          {showDissenting && (
            <ul className="list-disc list-inside text-gray-600 dark:text-gray-400 space-y-1 mt-3">
              {decision.dissenting_opinions.map((op, i) => (
                <li key={i}>{op}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Key Disagreements (P1.5) */}
      {hasKeyDisagreements && (
        <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <button
            onClick={() => setShowDisagreements(!showDisagreements)}
            className="w-full flex justify-between items-center"
          >
            <h3 className="font-semibold text-gray-700 dark:text-gray-300">
              Key Disagreements ({decision.key_disagreements!.length})
            </h3>
            <span className="text-gray-400 text-sm">{showDisagreements ? "▲" : "▼"}</span>
          </button>
          {showDisagreements && (
            <ul className="list-disc list-inside text-gray-600 dark:text-gray-400 space-y-1 mt-3">
              {decision.key_disagreements!.map((d, i) => (
                <li key={i} className="text-sm">{d}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Minority Report (P1.5) */}
      {hasMinorityReport && (
        <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <button
            onClick={() => setShowMinority(!showMinority)}
            className="w-full flex justify-between items-center"
          >
            <h3 className="font-semibold text-amber-700 dark:text-amber-400">
              Minority Report ({decision.minority_report!.length})
            </h3>
            <span className="text-gray-400 text-sm">{showMinority ? "▲" : "▼"}</span>
          </button>
          {showMinority && (
            <div className="mt-3 space-y-3">
              {decision.minority_report!.map((entry, i) => (
                <div key={i} className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-sm text-amber-800 dark:text-amber-300">
                      {entry.agent_name}
                    </span>
                    <span className="text-xs text-gray-500 tabular-nums">
                      {Math.round(entry.confidence_score * 100)}% confidence
                    </span>
                  </div>
                  <Markdown className="text-sm text-gray-700 dark:text-gray-300 mb-1">{entry.final_position}</Markdown>
                  <p className="text-xs text-amber-700 dark:text-amber-400 italic">{entry.dissent_reason}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={handleDownloadJSON}
          className="px-4 py-2 rounded-lg bg-gray-800 text-white text-sm font-medium hover:bg-gray-700 transition"
        >
          ⬇ JSON
        </button>
        {decision.debate_trace.length > 0 && (
          <button
            onClick={() => setShowTrace(!showTrace)}
            className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            {showTrace ? "Hide" : "View"} Full Debate Trace
          </button>
        )}
      </div>

      {/* Debate trace */}
      {showTrace && decision.debate_trace.length > 0 && (
        <section className="bg-gray-50 rounded-xl border p-6">
          <h3 className="font-semibold text-gray-700 mb-4">Debate Trace</h3>
          <DebateTimeline rounds={decision.debate_trace} />
        </section>
      )}

      {/* Sticky export action bar */}
      <div className="fixed bottom-0 left-0 right-0 z-20 bg-white/90 dark:bg-gray-900/95 backdrop-blur-md border-t border-gray-200 dark:border-gray-800 shadow-lg">
        <div className="max-w-4xl mx-auto px-4 py-2.5 flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-400 font-medium mr-1 hidden sm:block">Export:</span>
          <button
            onClick={() => handleExport("markdown")}
            disabled={exportLoading !== null}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 text-white text-xs font-medium hover:bg-gray-700 disabled:opacity-50 transition"
          >
            {exportLoading === "markdown" ? (
              <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : "⬇"}
            Markdown
          </button>
          <button
            onClick={() => handleExport("pdf")}
            disabled={exportLoading !== null}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-700 text-white text-xs font-medium hover:bg-red-800 disabled:opacity-50 transition"
          >
            {exportLoading === "pdf" ? (
              <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : "⬇"}
            PDF
          </button>
          <span className="text-gray-200 dark:text-gray-700 select-none">|</span>
          {/* Copy decision + permalink */}
          <button
            onClick={handleCopyDecision}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            ⧉ Copy
          </button>
          <button
            onClick={handleCopyLink}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            🔗 Link
          </button>
          <button
            onClick={handleDownloadJSON}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            ⬇ JSON
          </button>
          {decision.debate_trace.length > 0 && (
            <button
              onClick={() => setShowTrace(!showTrace)}
              className="ml-auto px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
            >
              {showTrace ? "▲ Hide" : "▼ Full Trace"}
            </button>
          )}
          {/* NB8: disable once a result is already loaded — re-fetching is redundant */}
          <button
            onClick={handleEvaluate}
            disabled={evalLoading || evalResult !== null}
            title={evalResult !== null ? "Evaluation already loaded (backend cached)" : undefined}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 text-white text-xs font-medium hover:bg-purple-700 disabled:opacity-40 transition"
          >
            {evalLoading ? (
              <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : evalResult !== null ? "✓" : "✦"}
            {evalResult !== null ? "Evaluated" : "Evaluate Quality"}
          </button>
        </div>
      </div>

      {/* P4.3 – Evaluation result panel */}
      {evalError && (
        <div className="fixed bottom-14 left-0 right-0 z-20 max-w-4xl mx-auto px-4">
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg px-4 py-2 text-xs text-red-700 dark:text-red-300">
            {evalError}
          </div>
        </div>
      )}
      {evalResult && (
        <div className="fixed bottom-14 left-0 right-0 z-20 max-w-4xl mx-auto px-4 pb-2">
          <div className="bg-white dark:bg-gray-900 border border-purple-200 dark:border-purple-700 rounded-xl shadow-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-semibold text-purple-700 dark:text-purple-300">
                Decision Quality — Overall {Math.round(evalResult.overall * 100)}%
              </h4>
              <button onClick={() => setEvalResult(null)} className="text-gray-400 hover:text-gray-600 text-sm">✕</button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
              {(["completeness", "consistency", "actionability", "risk_awareness"] as const).map((dim) => {
                const pct = Math.round(evalResult[dim] * 100);
                const color = pct >= 80 ? "bg-green-500" : pct >= 55 ? "bg-yellow-500" : "bg-red-500";
                return (
                  <div key={dim} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500 dark:text-gray-400 capitalize">{dim.replace("_", " ")}</span>
                      <span className="font-semibold tabular-nums">{pct}%</span>
                    </div>
                    <div className="h-1.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
            {evalResult.reasoning && (
              <p className="text-xs text-gray-500 dark:text-gray-400 italic leading-snug">{evalResult.reasoning}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
