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

  return (
    <div className="space-y-4">
      {/* Agent response grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {round.agent_outputs.map((output) => (
          <div key={output.agent_name} className="space-y-2">
            <AgentCard response={output} />

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
