/**
 * AgentCard – displays a single agent's response.
 *
 * Neutral raised card with a 4px accent rail in the agent's colour and an
 * AgentAvatar header — reads identically in light and dark mode.
 */

"use client";

import type { AgentResponse, Stance } from "@/lib/types";
import { AGENT_META, DOMAIN_AGENT_META } from "@/lib/types";
import ConfidenceMeter from "./ConfidenceMeter";
import Markdown from "./Markdown";
import AgentAvatar, { agentColor } from "./ui/AgentAvatar";

// Compact verdict chip shown next to the confidence meter.
const STANCE_CHIP: Record<Stance, { symbol: string; title: string; className: string }> = {
  support:     { symbol: "✓", title: "Supports the proposal",         className: "bg-green-50 text-green-700 ring-green-200 dark:bg-green-900/20 dark:text-green-300 dark:ring-green-800" },
  oppose:      { symbol: "✗", title: "Opposes the proposal",          className: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-900/20 dark:text-red-300 dark:ring-red-800" },
  conditional: { symbol: "~", title: "Supports only with conditions", className: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:ring-amber-800" },
  abstain:     { symbol: "–", title: "Abstains (no recommendation)",  className: "bg-gray-50 text-gray-500 ring-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:ring-gray-700" },
};

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
        <div className="flex items-center gap-2">
          {response.veto && (
            <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
              Veto
            </span>
          )}
          <span className="text-xs text-gray-400">Round {response.round_number}</span>
        </div>
      </div>

      {/* Body */}
      <div className="pl-5 pr-4 py-3 space-y-3 text-sm">
        {response.veto && (
          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 ring-1 ring-red-200 dark:ring-red-800 px-3 py-2">
            <p className="text-xs font-semibold text-red-700 dark:text-red-300">
              Veto — consensus is blocked while it stands
            </p>
            {response.veto_reason && (
              <p className="text-xs text-red-700/90 dark:text-red-300/90 mt-0.5">{response.veto_reason}</p>
            )}
          </div>
        )}
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

        {/* Confidence + stance */}
        <div className="flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <ConfidenceMeter score={response.confidence_score} label="Confidence" size="sm" />
          </div>
          {response.stance && STANCE_CHIP[response.stance] && (
            <span
              title={STANCE_CHIP[response.stance].title}
              aria-label={`Stance: ${response.stance}`}
              className={`shrink-0 w-6 h-6 rounded-full ring-1 flex items-center justify-center text-xs font-bold ${STANCE_CHIP[response.stance].className}`}
            >
              {STANCE_CHIP[response.stance].symbol}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
