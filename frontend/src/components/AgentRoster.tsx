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
import AgentAvatar from "./ui/AgentAvatar";

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
  /** When provided, the domain-pack selector renders inside this card. */
  onSelectDomainPack?: (id: string | null) => void;
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
  onSelectDomainPack,
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
    <div className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-4">
      {/* Domain pack selector — the pack overrides the roster below */}
      {onSelectDomainPack && domainPacks.length > 0 && (
        <div className="mb-3 pb-3 border-b border-line">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
            Domain pack <span className="font-normal normal-case">(optional)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {domainPacks.map((p) => {
              const active = selectedDomainPack === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onSelectDomainPack(active ? null : p.id)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-full border text-xs transition ${
                    active
                      ? "border-accent-500 bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-300"
                      : "border-line text-gray-600 dark:text-gray-400 hover:border-line-strong"
                  }`}
                >
                  <span>{p.icon}</span>
                  <span>{p.name}</span>
                </button>
              );
            })}
          </div>
          {pack && (
            <p className="mt-2 text-xs text-accent-700 dark:text-accent-300 leading-relaxed">
              {pack.description}
            </p>
          )}
        </div>
      )}

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
                  className={`inline-flex items-center gap-1.5 pl-1 pr-3 py-1 rounded-full text-xs font-medium border ${
                    m.isDomain
                      ? "border-violet-400 dark:border-violet-500 bg-violet-50 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300"
                      : "border-accent-500 bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-300"
                  }`}
                >
                  <AgentAvatar name={name} size="sm" />
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
          {agents.map(({ name, role }) => {
            const isSelected = selectedAgents.has(name);
            const isRequired = name === "Moderator";
            return (
              <button
                key={name}
                type="button"
                onClick={() => onToggle(name)}
                disabled={isRequired}
                title={isRequired ? "Moderator is always required" : role}
                className={`inline-flex items-center gap-1.5 pl-1 pr-3 py-1 rounded-full text-xs font-medium border transition
                  ${
                    isSelected
                      ? "border-accent-500 bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-300"
                      : "border-line-strong bg-surface-raised text-gray-500 dark:text-gray-400 opacity-60"
                  }
                  ${isRequired ? "cursor-default" : "hover:border-accent-400 cursor-pointer"}`}
              >
                <AgentAvatar name={name} size="sm" />
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
