/**
 * Agent memory management page.
 * View and clear per-agent learned memories from past debates.
 */

"use client";

import { useState, useEffect } from "react";
import { getAgentMemory, clearAgentMemory } from "@/lib/api";
import type { MemoryEntry } from "@/lib/api";

const KNOWN_AGENTS = [
  { name: "analyst", label: "Analyst", icon: "🔍" },
  { name: "risk", label: "Risk", icon: "⚠️" },
  { name: "strategy", label: "Strategy", icon: "🎯" },
  { name: "ethics", label: "Ethics", icon: "⚖️" },
  { name: "moderator", label: "Moderator", icon: "🧑‍⚖️" },
  { name: "financial_ethics", label: "Financial Ethics", icon: "💰" },
  { name: "security", label: "Security", icon: "🔒" },
  { name: "compliance", label: "Compliance", icon: "📋" },
  { name: "patient_safety", label: "Patient Safety", icon: "🏥" },
];

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
  const [memoryMap, setMemoryMap] = useState<Record<string, AgentMemoryState>>(
    () =>
      Object.fromEntries(
        KNOWN_AGENTS.map((a) => [
          a.name,
          { entries: [], loading: true, clearing: false, error: null },
        ])
      )
  );

  useEffect(() => {
    KNOWN_AGENTS.forEach((agent) => {
      getAgentMemory(agent.name, 20)
        .then((entries) =>
          setMemoryMap((prev) => ({
            ...prev,
            [agent.name]: { ...prev[agent.name], entries, loading: false },
          }))
        )
        .catch((err) =>
          setMemoryMap((prev) => ({
            ...prev,
            [agent.name]: {
              ...prev[agent.name],
              loading: false,
              error: err instanceof Error ? err.message : "Failed to load",
            },
          }))
        );
    });
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
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-1">Agent Memory</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Lessons and summaries accumulated by agents from past debates. Clear per-agent to reset.
        </p>
      </div>

      {KNOWN_AGENTS.map((agent) => {
        const state = memoryMap[agent.name];
        const hasEntries = state.entries.length > 0;

        return (
          <div key={agent.name} className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm">
            <div className="px-5 py-4 border-b dark:border-gray-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">{agent.icon}</span>
                <span className="font-semibold text-gray-800 dark:text-gray-100 text-sm">
                  {agent.label} Agent
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
                <div className="flex items-center gap-2 text-sm text-gray-400 py-2">
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  Loading…
                </div>
              ) : state.error ? (
                <p className="text-xs text-red-500 py-2">{state.error}</p>
              ) : !hasEntries ? (
                <p className="text-xs text-gray-400 py-2">No memories stored yet.</p>
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
