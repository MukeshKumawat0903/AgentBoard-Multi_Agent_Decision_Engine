/**
 * Agent memory management page.
 * View and clear per-agent learned memories from past debates.
 *
 * NB11: agent list is fetched live from GET /agents so new domain/custom
 * agents appear automatically without a frontend code change.
 * NB2: agent names are stored in title case ("Analyst") — COLLATE NOCASE
 * was added to the SQL query to make the lookup case-insensitive.
 */

"use client";

import { useState, useEffect } from "react";
import { getAgentMemory, clearAgentMemory, getAgents } from "@/lib/api";
import type { MemoryEntry } from "@/lib/api";
import type { AgentConfigResponse } from "@/lib/types";
import { SkeletonText } from "@/components/Skeleton";

interface AgentMemoryState {
  entries: MemoryEntry[];
  loading: boolean;
  clearing: boolean;
  error: string | null;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function MemoryPage() {
  const [agents, setAgents] = useState<AgentConfigResponse[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [memoryMap, setMemoryMap] = useState<Record<string, AgentMemoryState>>({});

  // NB11: fetch live agent list so domain/custom agents appear automatically
  useEffect(() => {
    getAgents()
      .then((list) => {
        setAgents(list);
        // Initialise memory state map for each agent
        const initial: Record<string, AgentMemoryState> = {};
        for (const a of list) {
          initial[a.name] = { entries: [], loading: true, clearing: false, error: null };
        }
        setMemoryMap(initial);
        // Load memory for each agent using the registry name (title case)
        for (const a of list) {
          getAgentMemory(a.name, 20)
            .then((entries) =>
              setMemoryMap((prev) => ({
                ...prev,
                [a.name]: { ...prev[a.name], entries, loading: false },
              }))
            )
            .catch((err) =>
              setMemoryMap((prev) => ({
                ...prev,
                [a.name]: {
                  ...prev[a.name],
                  loading: false,
                  error: err instanceof Error ? err.message : "Failed to load",
                },
              }))
            );
        }
      })
      .catch(() => setAgents([]))
      .finally(() => setAgentsLoading(false));
  }, []);

  async function handleClear(agentName: string) {
    setMemoryMap((prev) => ({
      ...prev,
      [agentName]: { ...prev[agentName], clearing: true },
    }));
    try {
      await clearAgentMemory(agentName);
      setMemoryMap((prev) => ({
        ...prev,
        [agentName]: { ...prev[agentName], entries: [], clearing: false },
      }));
    } catch (err) {
      setMemoryMap((prev) => ({
        ...prev,
        [agentName]: {
          ...prev[agentName],
          clearing: false,
          error: err instanceof Error ? err.message : "Failed to clear",
        },
      }));
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6 animate-fadeIn">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-gray-800 dark:text-gray-100 mb-1">Agent Memory</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Lessons and summaries accumulated by agents from past debates. Clear per-agent to reset.
        </p>
      </div>

      {agentsLoading && (
        <div className="py-8 flex justify-center">
          <span className="w-5 h-5 border-4 border-accent-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!agentsLoading && agents.length === 0 && (
        <p className="text-sm text-gray-400 py-4">No agents registered. Start the backend and reload.</p>
      )}

      {agents.map((agent) => {
        const state = memoryMap[agent.name] ?? { entries: [], loading: true, clearing: false, error: null };
        const hasEntries = state.entries.length > 0;

        return (
          <div key={agent.name} className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card">
            <div className="px-5 py-4 border-b border-line flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">{agent.icon}</span>
                <span className="font-semibold text-gray-800 dark:text-gray-100 text-sm">
                  {agent.name} Agent
                </span>
                {!state.loading && (
                  <span className="ml-1 text-xs text-gray-400">
                    ({state.entries.length} {state.entries.length === 1 ? "entry" : "entries"})
                  </span>
                )}
              </div>
              {hasEntries && (
                <button
                  onClick={() => handleClear(agent.name)}
                  disabled={state.clearing}
                  className="text-xs px-3 py-1.5 rounded-lg border border-red-300 dark:border-red-700
                             text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20
                             disabled:opacity-50 transition"
                >
                  {state.clearing ? "Clearing…" : "Clear Memory"}
                </button>
              )}
            </div>

            <div className="px-5 py-3">
              {state.loading ? (
                <div className="py-3">
                  <SkeletonText lines={3} />
                </div>
              ) : state.error ? (
                <p className="text-xs text-red-500 py-2">{state.error}</p>
              ) : !hasEntries ? (
                <div className="flex flex-col items-center gap-3 py-6 text-center">
                  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
                    <rect width="40" height="40" rx="10" className="fill-gray-100 dark:fill-gray-800" />
                    <circle cx="20" cy="16" r="5" className="fill-gray-300 dark:fill-gray-600" />
                    <rect x="10" y="25" width="20" height="3" rx="1.5" className="fill-gray-200 dark:fill-gray-700" />
                    <rect x="14" y="31" width="12" height="2.5" rx="1.25" className="fill-gray-200 dark:fill-gray-700" />
                  </svg>
                  <p className="text-xs text-gray-500 dark:text-gray-400">No memories stored yet.</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">Run a debate with <span className="font-medium">Agent Memory</span> enabled to populate this.</p>
                </div>
              ) : (
                <ul className="space-y-3 py-1">
                  {state.entries.map((entry, i) => (
                    <li key={i} className="bg-gray-50 dark:bg-gray-800 rounded-lg px-4 py-3">
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                          Debate {entry.debate_id ? `#${entry.debate_id.slice(-6)}` : "—"}
                        </span>
                        <span className="text-xs text-gray-400 shrink-0">
                          {timeAgo(entry.created_at)}
                        </span>
                      </div>
                      {/* FI8: lesson and summary are both visible inline */}
                      {entry.lesson_learned && (
                        <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">
                          {entry.lesson_learned}
                        </p>
                      )}
                      {entry.summary && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-snug">
                          {entry.summary}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
