/**
 * DebateInput – form for starting a new debate.
 *
 * Contains a textarea (min 10 chars), debate mode selector, and a submit
 * button with loading state. Supports AbortController-based cancellation
 * via an optional onCancel prop.
 */

"use client";

import { useState, useEffect, useRef, type FormEvent, type ChangeEvent } from "react";
import { getAgents } from "@/lib/api";

type DebateMode = "quick" | "standard" | "thorough";

const MODE_OPTIONS: { value: DebateMode; label: string; description: string }[] = [
  { value: "quick",    label: "⚡ Quick",    description: "2 rounds · No critiques · Threshold 0.60" },
  { value: "standard", label: "⚖️ Standard", description: "4 rounds · Full critique · Threshold 0.75" },
  { value: "thorough", label: "🔬 Thorough", description: "6 rounds · Full critique · Threshold 0.85" },
];

interface AgentOption { name: string; icon: string; role: string; }

const DEFAULT_AGENTS: AgentOption[] = [
  { name: "Analyst",   icon: "📊", role: "Objective data analyst" },
  { name: "Risk",      icon: "⚠️", role: "Adversarial risk assessor" },
  { name: "Strategy",  icon: "🎯", role: "Actionable strategy proposer" },
  { name: "Ethics",    icon: "⚖️", role: "Ethics and compliance guardian" },
  { name: "Moderator", icon: "🏛️", role: "Neutral synthesizer" },
];

export interface DebateOptions {
  mode: DebateMode;
  agents?: string[];
  use_knowledge_base?: boolean;
  enable_agent_memory?: boolean;
  supervised?: boolean;
  domain_pack?: string | null;
}

interface DebateInputProps {
  onSubmit: (query: string, options: DebateOptions) => void;
  onCancel?: () => void;
  isLoading: boolean;
  prefillQuery?: string;
  prefillMode?: DebateMode;
  selectedDomainPack?: string | null;
}

export default function DebateInput({
  onSubmit,
  onCancel,
  isLoading,
  prefillQuery,
  prefillMode,
  selectedDomainPack,
}: DebateInputProps) {
  const [query, setQuery] = useState(prefillQuery ?? "");
  const [mode, setMode] = useState<DebateMode>(prefillMode ?? "standard");
  const [touched, setTouched] = useState(false);
  const [showErrorState, setShowErrorState] = useState(false);
  const [isShaking, setIsShaking] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [agents, setAgents] = useState<AgentOption[]>(DEFAULT_AGENTS);
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(
    () => new Set(DEFAULT_AGENTS.map((a) => a.name))
  );
  const [useKnowledgeBase, setUseKnowledgeBase] = useState(false);
  const [enableAgentMemory, setEnableAgentMemory] = useState(false);
  const [supervised, setSupervised] = useState(false);

  useEffect(() => {
    getAgents()
      .then((res) => {
        if (res && res.length > 0) {
          setAgents(res.map((a) => ({ name: a.name, icon: a.icon, role: a.role })));
          setSelectedAgents(new Set(res.map((a) => a.name)));
        }
      })
      .catch(() => {}); // fall back to defaults
  }, []);

  // Auto-expand textarea height as content grows.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [query]);

  function toggleAgent(name: string) {
    if (name === "Moderator") return; // Moderator is always required
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        if (next.size <= 2) return prev; // must keep at least 2 agents
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (query.trim().length < 10) {
      // Trigger red border glow + shake animation on invalid submission.
      setShowErrorState(true);
      setIsShaking(true);
      setTimeout(() => setIsShaking(false), 300);
      return;
    }
    const allSelected = selectedAgents.size === agents.length;
    onSubmit(query.trim(), {
      mode,
      agents: allSelected ? undefined : [...selectedAgents],
      use_knowledge_base: useKnowledgeBase,
      enable_agent_memory: enableAgentMemory,
      supervised,
      domain_pack: selectedDomainPack ?? null,
    });
  }

  const queryTooShort = query.trim().length > 0 && query.trim().length < 10;
  const showInlineError = touched && queryTooShort;
  const charCount = query.length;

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Text area */}
      <div>
        <div className="flex justify-between items-center mb-1">
          <label
            htmlFor="query"
            className="block text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            What should the agents debate?
          </label>
          <span className={`text-xs tabular-nums ${charCount > 4800 ? "text-red-500" : "text-gray-400 dark:text-gray-500"}`}>
            {charCount} / 5000
          </span>
        </div>
        <textarea
          id="query"
          ref={textareaRef}
          value={query}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => {
            const val = e.target.value;
            setQuery(val);
            // Clear error glow as soon as the input becomes valid.
            if (showErrorState && val.trim().length >= 10) {
              setShowErrorState(false);
            }
          }}
          onBlur={() => setTouched(true)}
          placeholder="e.g. Should our company expand into the Asian market in Q3?"
          disabled={isLoading}
          maxLength={5000}
          className={`w-full rounded-lg border px-4 py-3 text-sm min-h-[96px] overflow-hidden
                     bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                     placeholder:text-gray-400 dark:placeholder:text-gray-500
                     focus:outline-none transition
                     disabled:bg-gray-50 dark:disabled:bg-gray-700 disabled:text-gray-400
                     ${showErrorState
                       ? "border-red-500 dark:border-red-500 ring-2 ring-red-400/30 focus:ring-red-500"
                       : "border-gray-300 dark:border-gray-600 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                     }
                     ${isShaking ? "animate-shake" : ""}`}
        />
        {showInlineError && (
          <p className="text-xs text-red-500 mt-1">
            Query must be at least 10 characters.
          </p>
        )}
      </div>

      {/* Debate mode selector */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Debate mode
        </label>
        <div className="grid grid-cols-3 gap-2">
          {MODE_OPTIONS.map(({ value, label, description }) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              disabled={isLoading}
              className={`rounded-lg border px-3 py-2.5 text-left text-xs transition
                ${mode === value
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                  : "border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-500"
                }
                disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              <div className="font-semibold mb-0.5">{label}</div>
              <div className="opacity-75 leading-snug">{description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Agent selector */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Participating agents
          </label>
          <span className="text-xs text-gray-400">
            {selectedAgents.size} / {agents.length} selected
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {agents.map(({ name, icon, role }) => {
            const isSelected = selectedAgents.has(name);
            const isRequired = name === "Moderator";
            return (
              <button
                key={name}
                type="button"
                onClick={() => toggleAgent(name)}
                disabled={isLoading || isRequired}
                title={isRequired ? "Moderator is always required" : role}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition
                  ${isSelected
                    ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                    : "border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 opacity-60"
                  }
                  ${isRequired ? "cursor-default" : "hover:border-blue-400 cursor-pointer"}
                  disabled:cursor-default`}
              >
                <span>{icon}</span>
                <span>{name}</span>
                {isRequired && <span className="opacity-60 text-xs">*</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* P3 Intelligence toggles */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2">
        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Intelligence options
        </p>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={useKnowledgeBase}
            onChange={(e) => setUseKnowledgeBase(e.target.checked)}
            disabled={isLoading}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Knowledge Base</span>
            <span className="text-gray-400 dark:text-gray-500 ml-1">– inject relevant documents into agent prompts</span>
            <a href="/knowledge" className="ml-2 text-blue-500 hover:underline text-xs">Manage docs ↗</a>
          </span>
        </label>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={enableAgentMemory}
            onChange={(e) => setEnableAgentMemory(e.target.checked)}
            disabled={isLoading}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Agent Memory</span>
            <span className="text-gray-400 dark:text-gray-500 ml-1">— use lessons learned from prior debates</span>
          </span>
        </label>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={supervised}
            onChange={(e) => setSupervised(e.target.checked)}
            disabled={isLoading}
            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500"
          />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Supervised mode</span>
            <span className="text-gray-400 dark:text-gray-500 ml-1">— pause for human review before finalising</span>
          </span>
        </label>
      </div>

      {/* Submit / Cancel */}
      <div className="flex gap-3">
        <button
          type="submit"
          disabled={isLoading || query.trim().length < 10}
          className="flex-1 py-3 rounded-lg bg-blue-600 text-white font-semibold text-sm
                     hover:bg-blue-700 focus:ring-2 focus:ring-blue-400 focus:ring-offset-2
                     disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {isLoading ? "Agents are debating…" : "Start Debate"}
        </button>
        {isLoading && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-3 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300
                       text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 transition"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

