/**
 * AgentCard – displays a single agent's response with colour-coded styling.
 */

"use client";

import type { AgentResponse, AgentName } from "@/lib/types";
import { AGENT_META } from "@/lib/types";
import ConfidenceMeter from "./ConfidenceMeter";

interface AgentCardProps {
  response: AgentResponse;
}

export default function AgentCard({ response }: AgentCardProps) {
  const meta = AGENT_META[response.agent_name as AgentName] ?? {
    name: response.agent_name,
    color: "#6B7280",
    lightColor: "#F3F4F6",
    icon: "🤖",
    role: "Agent",
  };

  return (
    <div
      className="rounded-xl border shadow-sm overflow-hidden dark:bg-gray-900"
      style={{ borderColor: meta.color }}
    >
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center justify-between dark:!bg-gray-800"
        style={{ backgroundColor: meta.lightColor }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xl">{meta.icon}</span>
          <div>
            <h3 className="font-semibold text-sm" style={{ color: meta.color }}>
              {meta.name}
            </h3>
            <p className="text-[11px] text-gray-500 dark:text-gray-400">{meta.role}</p>
          </div>
        </div>
        <span className="text-xs text-gray-400">Round {response.round_number}</span>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3 text-sm">
        {/* Position */}
        <div>
          <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-1">Position</h4>
          <p className="text-gray-600 dark:text-gray-400 whitespace-pre-line">{response.position}</p>
        </div>

        {/* Reasoning */}
        <div>
          <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-1">Reasoning</h4>
          <p className="text-gray-500 dark:text-gray-400 whitespace-pre-line">{response.reasoning}</p>
        </div>

        {/* Assumptions */}
        {response.assumptions && response.assumptions.length > 0 && (
          <div>
            <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-1">Assumptions</h4>
            <ul className="list-disc list-inside text-gray-500 dark:text-gray-400 space-y-0.5">
              {response.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Confidence */}
        <ConfidenceMeter score={response.confidence_score} label="Confidence" size="sm" />
      </div>
    </div>
  );
}
