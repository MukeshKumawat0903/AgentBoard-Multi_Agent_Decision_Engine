/**
 * DebateTimeline – vertical timeline displaying all rounds of a debate.
 */

"use client";

import { useState } from "react";
import type { DebateRound } from "@/lib/types";
import RoundView from "./RoundView";
import ConfidenceMeter from "./ConfidenceMeter";

interface DebateTimelineProps {
  rounds: DebateRound[];
  agreementScores?: number[]; // one per round (optional)
}

export default function DebateTimeline({
  rounds,
  agreementScores,
}: DebateTimelineProps) {
  const [expandedRound, setExpandedRound] = useState<number | null>(
    rounds.length > 0 ? rounds[rounds.length - 1].round_number : null,
  );

  if (rounds.length === 0) {
    return (
      <p className="text-gray-400 dark:text-gray-500 text-center py-8">No rounds available yet.</p>
    );
  }

  return (
    <div className="relative pl-8">
      {/* Vertical line */}
      <div className="absolute left-3 top-0 bottom-0 w-0.5 bg-gray-200 dark:bg-gray-700" />

      {rounds.map((round, idx) => {
        const isExpanded = expandedRound === round.round_number;
        const score = agreementScores?.[idx];

        return (
          <div key={round.round_number} className="relative mb-8">
            {/* Node dot */}
            <div className="absolute -left-5 top-1 w-4 h-4 rounded-full bg-blue-500 border-2 border-white dark:border-gray-900 shadow" />

            {/* Round header */}
            <button
              onClick={() =>
                setExpandedRound(isExpanded ? null : round.round_number)
              }
              className="w-full text-left group"
            >
              <div className="flex items-center gap-3">
                <h3 className="font-semibold text-gray-800 dark:text-gray-100">
                  Round {round.round_number}
                </h3>
                <span className="text-xs text-gray-400 capitalize">
                  {round.phase}
                </span>
                <span className="text-xs text-gray-400">
                  {round.agent_outputs.length} agents
                </span>
                {score !== undefined && (
                  <span className="text-xs text-gray-400">
                    Agreement: {Math.round(score * 100)}%
                  </span>
                )}
                <span className="text-xs text-blue-400 opacity-0 group-hover:opacity-100 transition">
                  {isExpanded ? "collapse" : "expand"}
                </span>
              </div>

              {/* Agreement bar */}
              {score !== undefined && (
                <div className="mt-1 max-w-xs">
                  <ConfidenceMeter score={score} size="sm" />
                </div>
              )}
            </button>

            {/* Expanded round content */}
            {isExpanded && (
              <div className="mt-4">
                <RoundView round={round} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
