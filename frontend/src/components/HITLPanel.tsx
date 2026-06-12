/**
 * HITLPanel – Human-in-the-Loop approval overlay.
 *
 * Shown when the backend emits an `approval_required` SSE event.
 * The user can approve the decision, provide an override, or grant
 * an extra debate round.
 */

"use client";

import { useState } from "react";
import type { ApprovalRequiredEvent } from "@/lib/types";
import { approveDebate } from "@/lib/api";

interface HITLPanelProps {
  event: ApprovalRequiredEvent;
  threadId: string;
  onDone: () => void;
}

export default function HITLPanel({ event, threadId, onDone }: HITLPanelProps) {
  const [feedback, setFeedback] = useState("");
  const [showFeedback, setShowFeedback] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAction(action: "approve" | "override" | "add_round") {
    if (action === "override" && !showFeedback) {
      setShowFeedback(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await approveDebate(threadId, action, action === "override" ? feedback : "");
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed.");
    } finally {
      setLoading(false);
    }
  }

  const agreementPct = Math.round(event.agreement_score * 100);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-surface-raised rounded-2xl shadow-2xl border border-purple-200 dark:border-purple-700 overflow-hidden">

        {/* Header */}
        <div className="bg-purple-50 dark:bg-purple-900/30 border-b border-purple-200 dark:border-purple-700 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⚖️</span>
            <div>
              <h2 className="font-bold text-gray-800 dark:text-gray-100">Human Review Required</h2>
              <p className="text-xs text-purple-600 dark:text-purple-400">
                Round {event.round_number} — Agreement {agreementPct}%
              </p>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* Synthesis summary */}
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">
              Synthesis Summary
            </p>
            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
              {event.synthesis_summary}
            </p>
          </div>

          {/* Termination reason */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-400">Reason:</span>
            <span className="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 font-medium capitalize">
              {event.termination_reason.replace(/_/g, " ")}
            </span>
          </div>

          {/* Override feedback textarea */}
          {showFeedback && (
            <div>
              <label className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1 block">
                Your override feedback
              </label>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={3}
                placeholder="Describe your preferred direction or decision…"
                className="w-full rounded-lg border border-line-strong px-3 py-2 text-sm
                           bg-surface-raised text-gray-900 dark:text-gray-100
                           placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 resize-y"
              />
            </div>
          )}

          {error && (
            <p className="text-xs text-red-500">{error}</p>
          )}
        </div>

        {/* Actions */}
        <div className="px-6 pb-6 flex flex-wrap gap-2">
          <button
            onClick={() => handleAction("approve")}
            disabled={loading}
            className="flex-1 py-2.5 rounded-lg bg-green-600 text-white text-sm font-semibold
                       hover:bg-green-700 disabled:opacity-50 transition"
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin inline-block" />
            ) : "✓ Approve"}
          </button>

          <button
            onClick={() => handleAction("add_round")}
            disabled={loading}
            className="flex-1 py-2.5 rounded-lg bg-accent-600 text-white text-sm font-semibold
                       hover:bg-accent-700 disabled:opacity-50 transition"
          >
            + Add Round
          </button>

          <button
            onClick={() => handleAction("override")}
            disabled={loading}
            className="flex-1 py-2.5 rounded-lg bg-purple-600 text-white text-sm font-semibold
                       hover:bg-purple-700 disabled:opacity-50 transition"
          >
            {showFeedback ? (
              loading ? (
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin inline-block" />
              ) : "Submit Override"
            ) : "✎ Override"}
          </button>
        </div>
      </div>
    </div>
  );
}
