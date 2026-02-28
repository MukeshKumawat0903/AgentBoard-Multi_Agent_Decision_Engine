/**
 * CritiqueView – shows critiques targeting a specific agent.
 */

"use client";

import type { CritiqueResponse, AgentName } from "@/lib/types";
import { AGENT_META } from "@/lib/types";

const SEVERITY_STYLES: Record<string, string> = {
  low: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300",
  medium: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-800 dark:text-yellow-300",
  high: "bg-orange-100 dark:bg-orange-900/40 text-orange-800 dark:text-orange-300",
  critical: "bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300",
};

interface CritiqueViewProps {
  critiques: CritiqueResponse[];
}

export default function CritiqueView({ critiques }: CritiqueViewProps) {
  if (critiques.length === 0) return null;

  return (
    <div className="space-y-2">
      {critiques.map((c, idx) => {
        const criticMeta = AGENT_META[c.critic_agent as AgentName];
        return (
          <div
            key={idx}
            className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm"
          >
            {/* Critic name + severity */}
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium" style={{ color: criticMeta?.color ?? "#6B7280" }}>
                {criticMeta?.icon ?? "🤖"} {c.critic_agent}
              </span>
              <span
                className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${SEVERITY_STYLES[c.severity] ?? SEVERITY_STYLES.low}`}
              >
                {c.severity}
              </span>
            </div>

            {/* Critique points */}
            <ul className="list-disc list-inside text-gray-600 dark:text-gray-400 space-y-0.5 ml-1">
              {c.critique_points.map((pt, j) => (
                <li key={j}>{pt}</li>
              ))}
            </ul>

            {/* Suggested revision */}
            {c.suggested_revision && (
              <p className="mt-1 text-gray-500 dark:text-gray-400 italic">
                Suggestion: {c.suggested_revision}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
