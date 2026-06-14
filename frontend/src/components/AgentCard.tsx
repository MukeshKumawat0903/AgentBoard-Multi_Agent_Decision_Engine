/**
 * AgentCard – displays a single agent's response.
 *
 * Neutral raised card with a 4px accent rail in the agent's colour and an
 * AgentAvatar header — reads identically in light and dark mode.
 */

"use client";

import type { AgentResponse } from "@/lib/types";
import { AGENT_META, DOMAIN_AGENT_META } from "@/lib/types";
import ConfidenceMeter from "./ConfidenceMeter";
import Markdown from "./Markdown";
import AgentAvatar, { agentColor } from "./ui/AgentAvatar";

interface AgentCardProps {
  response: AgentResponse;
}

export default function AgentCard({ response }: AgentCardProps) {
  const name = response.agent_name;
  const meta =
    AGENT_META[name as keyof typeof AGENT_META] ??
    DOMAIN_AGENT_META[name] ??
    { name, role: "Agent" };
  const color = agentColor(name);

  return (
    <div className="relative overflow-hidden rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-hover">
      {/* Accent rail */}
      <span
        aria-hidden="true"
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ backgroundColor: color }}
      />

      {/* Header */}
      <div className="pl-5 pr-4 py-3 flex items-center justify-between border-b border-line">
        <div className="flex items-center gap-2.5">
          <AgentAvatar name={name} size="md" />
          <div>
            <h3 className="font-semibold text-sm text-gray-800 dark:text-gray-100">
              {meta.name}
            </h3>
            <p className="text-[11px] text-gray-500 dark:text-gray-400">{meta.role}</p>
          </div>
        </div>
        <span className="text-xs text-gray-400">Round {response.round_number}</span>
      </div>

      {/* Body */}
      <div className="pl-5 pr-4 py-3 space-y-3 text-sm">
        {/* Position */}
        <div>
          <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-1">Position</h4>
          <Markdown className="text-gray-600 dark:text-gray-400">{response.position}</Markdown>
        </div>

        {/* Reasoning */}
        <div>
          <h4 className="font-medium text-gray-700 dark:text-gray-300 mb-1">Reasoning</h4>
          <Markdown className="text-gray-500 dark:text-gray-400">{response.reasoning}</Markdown>
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
