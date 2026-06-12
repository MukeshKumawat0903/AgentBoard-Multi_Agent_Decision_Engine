/**
 * AgentRoster – right-rail panel showing the agents that will debate.
 *
 * Two modes:
 *  - No domain pack: the enabled core agents are shown as interactive toggles.
 *  - Domain pack selected: the pack defines the roster (the backend overrides
 *    the per-agent selection), so the pack's agents are shown read-only.
 *
 * A live "core / domain" breakdown makes the composition explicit instead of
 * the previous confusing "9 / 9 selected" count.
 */

"use client";

import { AGENT_META, DOMAIN_AGENT_META, type DomainPack } from "@/lib/types";

export interface AgentOption {
  name: string;
  icon: string;
  role: string;
}

interface AgentRosterProps {
  agents: AgentOption[];
  selectedAgents: Set<string>;
  onToggle: (name: string) => void;
  selectedDomainPack: string | null;
  domainPacks: DomainPack[];
}

function metaFor(name: string): { icon: string; role: string; isDomain: boolean } {
  if (name in AGENT_META) {
    const m = AGENT_META[name as keyof typeof AGENT_META];
    return { icon: m.icon, role: m.role, isDomain: false };
  }
  if (name in DOMAIN_AGENT_META) {
    const m = DOMAIN_AGENT_META[name];
    return { icon: m.icon, role: m.role, isDomain: true };
  }
  return { icon: "🤖", role: "", isDomain: false };
}

export default function AgentRoster({
  agents,
  selectedAgents,
  onToggle,
  selectedDomainPack,
  domainPacks,
}: AgentRosterProps) {
  const pack = selectedDomainPack
    ? domainPacks.find((p) => p.id === selectedDomainPack) ?? null
    : null;

  // The active roster: a domain pack overrides the agent list entirely.
  const rosterNames = pack
    ? pack.agents
    : agents.filter((a) => selectedAgents.has(a.name)).map((a) => a.name);
  const coreCount = rosterNames.filter((n) => !metaFor(n).isDomain).length;
  const domainCount = rosterNames.length - coreCount;

  const breakdown =
    domainCount > 0
      ? `${coreCount} core · ${domainCount} domain expert${domainCount > 1 ? "s" : ""}`
      : `${coreCount} core agent${coreCount !== 1 ? "s" : ""}`;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Agents
        </p>
        <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
          {rosterNames.length} active
        </span>
      </div>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{breakdown}</p>

      {pack ? (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            {pack.agents.map((name) => {
              const m = metaFor(name);
              return (
                <span
                  key={name}
                  title={m.role}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ${
                    m.isDomain
                      ? "border-violet-400 dark:border-violet-500 bg-violet-50 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300"
                      : "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                  }`}
                >
                  <span>{m.icon}</span>
                  <span>{name}</span>
                </span>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
            Roster set by the <span className="font-medium">{pack.name}</span> domain pack.
          </p>
        </>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {agents.map(({ name, icon, role }) => {
            const isSelected = selectedAgents.has(name);
            const isRequired = name === "Moderator";
            return (
              <button
                key={name}
                type="button"
                onClick={() => onToggle(name)}
                disabled={isRequired}
                title={isRequired ? "Moderator is always required" : role}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition
                  ${
                    isSelected
                      ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                      : "border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 opacity-60"
                  }
                  ${isRequired ? "cursor-default" : "hover:border-blue-400 cursor-pointer"}`}
              >
                <span>{icon}</span>
                <span>{name}</span>
                {isRequired && <span className="opacity-60 text-xs">*</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
