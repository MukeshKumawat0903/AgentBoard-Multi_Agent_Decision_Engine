/**
 * RoundView – renders all agent cards + critiques for a single debate round.
 */

"use client";

import { useState } from "react";
import type { DebateRound } from "@/lib/types";
import AgentCard from "./AgentCard";
import CritiqueView from "./CritiqueView";

interface RoundViewProps {
  round: DebateRound;
}

export default function RoundView({ round }: RoundViewProps) {
  const [showCritiques, setShowCritiques] = useState(false);
  // Tools shown in the persisted trace come from `tool_calls`; live view uses `toolCalls`.
  const toolCalls = round.tool_calls ?? round.toolCalls ?? [];

  return (
    <div className="space-y-4">
      {/* Agent response grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {round.agent_outputs.map((output) => (
          <div key={output.agent_name} className="space-y-2">
            <AgentCard response={output} />

            {/* Tool activity for this agent */}
            {toolCalls
              .filter((tc) => tc.agent_name === output.agent_name)
              .map((tc, i) => (
                <div
                  key={i}
                  className="text-xs bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2 flex items-start gap-2"
                >
                  <span className="shrink-0">🔧</span>
                  <span>
                    <span className="font-medium text-amber-700 dark:text-amber-400">{tc.tool_name}</span>
                    {tc.output_snippet && (
                      <span className="text-gray-500 dark:text-gray-400 ml-1">
                        → {tc.output_snippet.slice(0, 120)}
                        {tc.output_snippet.length > 120 ? "…" : ""}
                      </span>
                    )}
                  </span>
                </div>
              ))}

            {/* Inline critique toggle per agent */}
            {showCritiques && (
              <CritiqueView
                critiques={round.critiques.filter(
                  (c) => c.target_agent === output.agent_name,
                )}
              />
            )}
          </div>
        ))}
      </div>

      {/* Toggle critiques */}
      {round.critiques.length > 0 && (
        <button
          onClick={() => setShowCritiques((prev) => !prev)}
          className="text-sm text-blue-500 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition font-medium"
        >
          {showCritiques
            ? "Hide critiques"
            : `Show ${round.critiques.length} critiques`}
        </button>
      )}
    </div>
  );
}
