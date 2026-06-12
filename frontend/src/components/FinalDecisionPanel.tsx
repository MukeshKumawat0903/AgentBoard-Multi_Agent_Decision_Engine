/**
 * FinalDecisionPanel – prominently displays the FinalDecision from a debate.
 *
 * Layout: verdict hero (decision + rationale + radial score gauges + run
 * metrics), then an accordion group for the secondary sections, then a
 * slim sticky export bar.
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import {
  AlertTriangle,
  BarChart3,
  Check,
  ChevronUp,
  Coins,
  Copy,
  Download,
  Flag,
  Link2,
  MessageSquareX,
  Repeat,
  Route,
  Sparkles,
  Swords,
  X,
} from "lucide-react";
import type { FinalDecision, EvaluationResult } from "@/lib/types";
import { evaluateDecision, exportDecision } from "@/lib/api";
import Markdown from "./Markdown";
import Badge, { type BadgeTone } from "./ui/Badge";
import Button from "./ui/Button";
import Card from "./ui/Card";
import CollapsibleSection from "./ui/CollapsibleSection";
import RadialGauge from "./ui/RadialGauge";
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

const TERMINATION_TONE: Record<string, BadgeTone> = {
  consensus_reached: "success",
  max_rounds_reached: "warning",
  human_override: "violet",
};

/** Shared header styling for the accordion group sections. */
const SECTION_HEADER = "px-5 py-3.5 hover:bg-surface transition-colors";
const SECTION_BODY = "px-5 pb-4";
const SECTION_TITLE = "text-sm font-semibold text-gray-700 dark:text-gray-300";

export default function FinalDecisionPanel({ decision }: FinalDecisionPanelProps) {
  const { showToast } = useToast();
  const [showMinority, setShowMinority] = useLocalBool("fdp:showMinority", false);
  const [showDisagreements, setShowDisagreements] = useLocalBool("fdp:showDisagreements", false);
  const [showDissenting, setShowDissenting] = useLocalBool("fdp:showDissenting", false);
  const [exportLoading, setExportLoading] = useState<null | "markdown" | "pdf" | "json">(null);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
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
    setExportMenuOpen(false);
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
    setExportMenuOpen(false);
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
  const hasSecondarySections =
    decision.risk_flags.length > 0 ||
    decision.alternatives.length > 0 ||
    decision.dissenting_opinions.length > 0 ||
    hasKeyDisagreements ||
    hasMinorityReport ||
    hasContributions;

  const exportButtons = (
    <>
      <Button size="sm" variant="outline" onClick={() => handleExport("markdown")}
              disabled={exportLoading !== null} loading={exportLoading === "markdown"}>
        {exportLoading !== "markdown" && <Download className="w-3.5 h-3.5" aria-hidden="true" />}
        Markdown
      </Button>
      <Button size="sm" variant="outline" onClick={() => handleExport("pdf")}
              disabled={exportLoading !== null} loading={exportLoading === "pdf"}>
        {exportLoading !== "pdf" && <Download className="w-3.5 h-3.5" aria-hidden="true" />}
        PDF
      </Button>
      <Button size="sm" variant="outline" onClick={handleDownloadJSON} disabled={exportLoading !== null}>
        <Download className="w-3.5 h-3.5" aria-hidden="true" />
        JSON
      </Button>
    </>
  );

  return (
    <div className="space-y-5 pb-24">
      {/* Degraded-run warning: decision rested on fewer agents than expected */}
      {decision.degraded && (
        <div className="flex items-start gap-3 rounded-2xl ring-1 ring-amber-300 dark:ring-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4">
          <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" aria-hidden="true" />
          <p className="text-sm text-amber-800 dark:text-amber-300 leading-relaxed">
            This decision was made with reduced input — the following agent
            {(decision.missing_agents?.length ?? 0) > 1 ? "s" : ""} did not contribute to the
            final round:{" "}
            <span className="font-semibold">{(decision.missing_agents ?? []).join(", ")}</span>.
            Treat it with extra caution.
          </p>
        </div>
      )}

      {/* Verdict hero — decision, rationale and the numbers in one card */}
      <section className="relative overflow-hidden rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card">
        <span
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-accent-500 via-violet-500 to-accent-400"
        />
        <div className="p-6 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_200px] gap-6">
          {/* Decision + rationale */}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <p className="text-xs font-bold uppercase tracking-wider text-accent-600 dark:text-accent-400">
                Decision
              </p>
              <Badge tone={TERMINATION_TONE[decision.termination_reason] ?? "neutral"} className="capitalize">
                {decision.termination_reason.replace(/_/g, " ")}
              </Badge>
            </div>
            <Markdown className="text-xl font-medium text-gray-800 dark:text-gray-100 leading-snug">
              {decision.decision}
            </Markdown>
            <hr className="my-4 border-line" />
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1.5">Rationale</h3>
            <Markdown className="text-sm text-gray-600 dark:text-gray-400">
              {decision.rationale_summary}
            </Markdown>
          </div>

          {/* Stat column */}
          <div className="flex md:flex-col items-center justify-around md:justify-start gap-4 md:gap-5 md:border-l md:border-line md:pl-6">
            <div className="flex gap-4">
              <RadialGauge score={decision.agreement_score} label="Agreement" />
              <RadialGauge score={decision.confidence_score} label="Confidence" />
            </div>
            <div className="space-y-1.5 text-xs text-gray-500 dark:text-gray-400">
              <p className="flex items-center gap-1.5">
                <Repeat className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                <span className="tabular-nums">
                  {decision.total_rounds} round{decision.total_rounds > 1 ? "s" : ""}
                </span>
              </p>
              {decision.token_usage && decision.token_usage.total_tokens > 0 && (
                <p
                  className="flex items-center gap-1.5"
                  title={`${decision.token_usage.input_tokens.toLocaleString()} in · ${decision.token_usage.output_tokens.toLocaleString()} out`}
                >
                  <Coins className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                  <span className="tabular-nums">
                    {decision.token_usage.total_tokens.toLocaleString()} tokens
                    {typeof decision.estimated_cost_usd === "number"
                      ? ` · ~$${decision.estimated_cost_usd.toFixed(4)}`
                      : ""}
                  </span>
                </p>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Secondary sections — one accordion group */}
      {hasSecondarySections && (
        <Card padded={false} className="divide-y divide-line overflow-hidden">
          {decision.risk_flags.length > 0 && (
            <CollapsibleSection
              defaultOpen
              headerClassName={SECTION_HEADER}
              bodyClassName={SECTION_BODY}
              title={
                <span className={`flex items-center gap-2 ${SECTION_TITLE}`}>
                  <AlertTriangle className="w-4 h-4 text-red-500" aria-hidden="true" />
                  Risk Flags
                </span>
              }
              meta={<Badge tone="danger">{decision.risk_flags.length}</Badge>}
            >
              <div className="flex flex-wrap gap-2">
                {decision.risk_flags.map((flag, i) => (
                  <Badge key={i} tone="danger" className="!text-sm !px-3 !py-1">
                    {flag}
                  </Badge>
                ))}
              </div>
            </CollapsibleSection>
          )}

          {hasContributions && (
            <CollapsibleSection
              defaultOpen
              headerClassName={SECTION_HEADER}
              bodyClassName={SECTION_BODY}
              title={
                <span className={`flex items-center gap-2 ${SECTION_TITLE}`}>
                  <BarChart3 className="w-4 h-4 text-accent-500" aria-hidden="true" />
                  Agent Contributions
                </span>
              }
            >
              <div className="space-y-2">
                {Object.entries(decision.agent_contribution_scores!).map(([agent, score]) => (
                  <div key={agent} className="flex items-center gap-3">
                    <span className="text-sm text-gray-600 dark:text-gray-400 w-24 truncate">{agent}</span>
                    <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-accent-500 rounded-full transition-all duration-500"
                        style={{ width: `${Math.round(score * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 tabular-nums w-10 text-right">
                      {Math.round(score * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </CollapsibleSection>
          )}

          {decision.alternatives.length > 0 && (
            <CollapsibleSection
              defaultOpen
              headerClassName={SECTION_HEADER}
              bodyClassName={SECTION_BODY}
              title={
                <span className={`flex items-center gap-2 ${SECTION_TITLE}`}>
                  <Route className="w-4 h-4 text-gray-400" aria-hidden="true" />
                  Alternatives Considered
                </span>
              }
              meta={<Badge tone="neutral">{decision.alternatives.length}</Badge>}
            >
              <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-400 space-y-1">
                {decision.alternatives.map((alt, i) => (
                  <li key={i}>{alt}</li>
                ))}
              </ul>
            </CollapsibleSection>
          )}

          {decision.dissenting_opinions.length > 0 && (
            <CollapsibleSection
              open={showDissenting}
              onToggle={setShowDissenting}
              headerClassName={SECTION_HEADER}
              bodyClassName={SECTION_BODY}
              title={
                <span className={`flex items-center gap-2 ${SECTION_TITLE}`}>
                  <MessageSquareX className="w-4 h-4 text-gray-400" aria-hidden="true" />
                  Dissenting Opinions
                </span>
              }
              meta={<Badge tone="neutral">{decision.dissenting_opinions.length}</Badge>}
            >
              <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-400 space-y-1">
                {decision.dissenting_opinions.map((op, i) => (
                  <li key={i}>{op}</li>
                ))}
              </ul>
            </CollapsibleSection>
          )}

          {hasKeyDisagreements && (
            <CollapsibleSection
              open={showDisagreements}
              onToggle={setShowDisagreements}
              headerClassName={SECTION_HEADER}
              bodyClassName={SECTION_BODY}
              title={
                <span className={`flex items-center gap-2 ${SECTION_TITLE}`}>
                  <Swords className="w-4 h-4 text-gray-400" aria-hidden="true" />
                  Key Disagreements
                </span>
              }
              meta={<Badge tone="neutral">{decision.key_disagreements!.length}</Badge>}
            >
              <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-400 space-y-1">
                {decision.key_disagreements!.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </CollapsibleSection>
          )}

          {hasMinorityReport && (
            <CollapsibleSection
              open={showMinority}
              onToggle={setShowMinority}
              headerClassName={SECTION_HEADER}
              bodyClassName={SECTION_BODY}
              title={
                <span className="flex items-center gap-2 text-sm font-semibold text-amber-700 dark:text-amber-400">
                  <Flag className="w-4 h-4" aria-hidden="true" />
                  Minority Report
                </span>
              }
              meta={<Badge tone="warning">{decision.minority_report!.length}</Badge>}
            >
              <div className="space-y-3">
                {decision.minority_report!.map((entry, i) => (
                  <div key={i} className="rounded-lg bg-amber-50 dark:bg-amber-900/20 ring-1 ring-amber-200 dark:ring-amber-700 p-4">
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
            </CollapsibleSection>
          )}
        </Card>
      )}

      {/* Evaluation result / error — inline, above the sticky bar */}
      {evalError && (
        <div className="bg-red-50 dark:bg-red-900/20 ring-1 ring-red-300 dark:ring-red-700 rounded-lg px-4 py-2 text-xs text-red-700 dark:text-red-300">
          {evalError}
        </div>
      )}
      {evalResult && (
        <Card padded={false} className="p-4 !ring-purple-200 dark:!ring-purple-700 animate-slideUpIn">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-semibold text-purple-700 dark:text-purple-300">
              Decision Quality — Overall {Math.round(evalResult.overall * 100)}%
            </h4>
            <button
              onClick={() => setEvalResult(null)}
              aria-label="Dismiss evaluation"
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
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
        </Card>
      )}

      {/* Sticky export action bar */}
      <div className="fixed bottom-0 left-0 right-0 z-20 bg-surface-overlay/90 backdrop-blur-md border-t border-line shadow-lg">
        <div className="max-w-6xl mx-auto px-4 py-2.5 flex flex-wrap items-center gap-2">
          {/* Mobile: single Export menu */}
          <div className="relative sm:hidden">
            <Button size="sm" variant="outline" onClick={() => setExportMenuOpen((v) => !v)}
                    aria-expanded={exportMenuOpen} aria-haspopup="menu">
              <Download className="w-3.5 h-3.5" aria-hidden="true" />
              Export
              <ChevronUp
                className={`w-3.5 h-3.5 transition-transform ${exportMenuOpen ? "" : "rotate-180"}`}
                aria-hidden="true"
              />
            </Button>
            {exportMenuOpen && (
              <div className="absolute bottom-full mb-2 left-0 flex flex-col gap-1 p-2 rounded-xl bg-surface-overlay ring-1 ring-black/5 dark:ring-white/10 shadow-card-hover">
                {exportButtons}
              </div>
            )}
          </div>
          {/* Desktop: inline export buttons */}
          <span className="text-xs text-gray-400 font-medium mr-1 hidden sm:block">Export:</span>
          <div className="hidden sm:flex items-center gap-2">{exportButtons}</div>

          <span className="text-line-strong select-none hidden sm:inline">|</span>
          <Button size="sm" variant="outline" onClick={handleCopyDecision}>
            <Copy className="w-3.5 h-3.5" aria-hidden="true" />
            Copy
          </Button>
          <Button size="sm" variant="outline" onClick={handleCopyLink}>
            <Link2 className="w-3.5 h-3.5" aria-hidden="true" />
            Link
          </Button>
          <Button
            size="sm"
            variant="primary"
            onClick={handleEvaluate}
            disabled={evalLoading || evalResult !== null}
            loading={evalLoading}
            title={evalResult !== null ? "Evaluation already loaded (backend cached)" : undefined}
            className="ml-auto"
          >
            {!evalLoading && (evalResult !== null
              ? <Check className="w-3.5 h-3.5" aria-hidden="true" />
              : <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />)}
            {evalResult !== null ? "Evaluated" : "Evaluate Quality"}
          </Button>
        </div>
      </div>
    </div>
  );
}
