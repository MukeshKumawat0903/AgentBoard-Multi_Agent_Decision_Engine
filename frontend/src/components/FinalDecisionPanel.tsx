/**
 * FinalDecisionPanel – prominently displays the FinalDecision from a debate.
 */

"use client";

import { useState } from "react";
import type { FinalDecision } from "@/lib/types";
import ConfidenceMeter from "./ConfidenceMeter";
import DebateTimeline from "./DebateTimeline";

interface FinalDecisionPanelProps {
  decision: FinalDecision;
}

export default function FinalDecisionPanel({ decision }: FinalDecisionPanelProps) {
  const [showTrace, setShowTrace] = useState(false);

  function handleDownload() {
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

  return (
    <div className="space-y-6">
      {/* Decision */}
      <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-2">Decision</h2>
        <p className="text-lg text-gray-700 dark:text-gray-300 leading-relaxed">
          {decision.decision}
        </p>
      </section>

      {/* Rationale */}
      <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
        <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2">Rationale</h3>
        <p className="text-gray-600 dark:text-gray-400">{decision.rationale_summary}</p>
      </section>

      {/* Scores */}
      <section className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6 grid grid-cols-1 sm:grid-cols-2 gap-6">
        <ConfidenceMeter score={decision.confidence_score} label="Confidence" />
        <ConfidenceMeter score={decision.agreement_score} label="Agreement" />
      </section>

      {/* Meta badges */}
      <div className="flex flex-wrap gap-3 text-sm">
        <span className="px-3 py-1 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium">
          {decision.total_rounds} round{decision.total_rounds > 1 ? "s" : ""}
        </span>
        <span className="px-3 py-1 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 font-medium capitalize">
          {decision.termination_reason.replace(/_/g, " ")}
        </span>
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
          <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2">Dissenting Opinions</h3>
          <ul className="list-disc list-inside text-gray-600 dark:text-gray-400 space-y-1">
            {decision.dissenting_opinions.map((op, i) => (
              <li key={i}>{op}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={handleDownload}
          className="px-4 py-2 rounded-lg bg-gray-800 text-white text-sm font-medium hover:bg-gray-700 transition"
        >
          Download JSON
        </button>
        {decision.debate_trace.length > 0 && (
          <button
            onClick={() => setShowTrace((prev) => !prev)}
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
    </div>
  );
}
