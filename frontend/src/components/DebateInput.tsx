/**
 * DebateInput – form for starting a new debate.
 *
 * Contains a textarea (min 10 chars), debate mode selector, intelligence
 * options, and a submit button with loading state. Supports
 * AbortController-based cancellation via an optional onCancel prop.
 *
 * The participating-agent roster lives in the right-rail AgentRoster; this
 * form receives the agent list and current selection as props and folds them
 * into the submit payload.
 */

"use client";

import { useState, useEffect, useRef, type FormEvent, type ChangeEvent } from "react";
import { Check, Microscope, SlidersHorizontal, Sparkles, Zap, type LucideIcon } from "lucide-react";
import type { AgentOption } from "./AgentRoster";
import Toggle from "./Toggle";
import Button from "./ui/Button";

type DebateMode = "quick" | "standard" | "thorough";

const MODE_OPTIONS: {
  value: DebateMode;
  label: string;
  Icon: LucideIcon;
  duration: string;
  description: string;
}[] = [
  { value: "quick",    label: "Quick",    Icon: Zap,               duration: "~30 s",    description: "2 rounds · No critiques · Threshold 0.60" },
  { value: "standard", label: "Standard", Icon: SlidersHorizontal, duration: "~1–2 min", description: "4 rounds · Full critique · Threshold 0.75" },
  { value: "thorough", label: "Thorough", Icon: Microscope,        duration: "~3 min",   description: "6 rounds · Full critique · Threshold 0.85" },
];

/** One-click starter questions shown under the textarea for first-time users. */
export interface SampleQuestion {
  label: string;
  query: string;
}

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
  agents: AgentOption[];
  selectedAgents: Set<string>;
  prefillQuery?: string;
  prefillMode?: DebateMode;
  selectedDomainPack?: string | null;
  samples?: SampleQuestion[];
}

export default function DebateInput({
  onSubmit,
  onCancel,
  isLoading,
  agents,
  selectedAgents,
  prefillQuery,
  prefillMode,
  selectedDomainPack,
  samples,
}: DebateInputProps) {
  const [query, setQuery] = useState(prefillQuery ?? "");
  const [mode, setMode] = useState<DebateMode>(prefillMode ?? "standard");
  const [touched, setTouched] = useState(false);
  const [showErrorState, setShowErrorState] = useState(false);
  const [isShaking, setIsShaking] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [useKnowledgeBase, setUseKnowledgeBase] = useState(false);
  const [enableAgentMemory, setEnableAgentMemory] = useState(false);
  const [supervised, setSupervised] = useState(false);

  // Auto-expand textarea height as content grows.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [query]);

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
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Text area */}
      <div>
        <div className="flex justify-between items-center mb-1">
          <label
            htmlFor="query"
            className="block text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            What should the agents debate?
          </label>
          <span className={`text-xs tabular-nums ${charCount > 4800 ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
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
          className={`w-full rounded-lg border px-4 py-2.5 text-sm min-h-[76px] overflow-hidden
                     bg-surface-raised text-gray-900 dark:text-gray-100
                     placeholder:text-gray-400 dark:placeholder:text-gray-500
                     focus:outline-none transition
                     disabled:bg-gray-50 dark:disabled:bg-gray-800 disabled:text-gray-400
                     ${showErrorState
                       ? "border-red-500 dark:border-red-500 ring-2 ring-red-400/30 focus:ring-red-500"
                       : "border-line-strong focus:ring-2 focus:ring-accent-500 focus:border-transparent"
                     }
                     ${isShaking ? "animate-shake" : ""}`}
        />
        {showInlineError && (
          <p className="text-xs text-red-500 mt-1">
            Query must be at least 10 characters.
          </p>
        )}

        {/* Sample question chips — shown until the user starts typing */}
        {samples && samples.length > 0 && query.trim().length === 0 && !isLoading && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
              <Sparkles className="w-3 h-3" aria-hidden="true" /> Try:
            </span>
            {samples.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => {
                  setQuery(s.query);
                  textareaRef.current?.focus();
                }}
                className="text-xs px-2.5 py-1 rounded-full border border-line text-gray-600 dark:text-gray-300
                           hover:border-accent-400 hover:text-accent-700 dark:hover:text-accent-300
                           hover:bg-accent-50 dark:hover:bg-accent-900/20 transition"
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Debate mode selector */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Debate mode
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {MODE_OPTIONS.map(({ value, label, Icon, duration, description }) => {
            const selected = mode === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                disabled={isLoading}
                aria-pressed={selected}
                title={description}
                className={`rounded-xl border px-3 py-2 text-left text-xs transition
                  ${selected
                    ? "border-accent-500 ring-1 ring-accent-500 bg-accent-50 dark:bg-accent-900/20 text-accent-700 dark:text-accent-300"
                    : "border-line bg-surface-raised text-gray-600 dark:text-gray-400 hover:border-line-strong"
                  }
                  disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                <span className="flex items-center gap-1.5">
                  <Icon
                    className={`w-4 h-4 shrink-0 ${selected ? "text-accent-600 dark:text-accent-400" : "text-gray-400"}`}
                    aria-hidden="true"
                  />
                  <span className="font-semibold text-sm">{label}</span>
                  <span className="ml-auto text-[10px] font-medium uppercase tracking-wide opacity-70">{duration}</span>
                  {selected && (
                    <span
                      aria-hidden="true"
                      className="w-4 h-4 rounded-full bg-accent-600 text-white flex items-center justify-center shrink-0"
                    >
                      <Check className="w-2.5 h-2.5" strokeWidth={3} />
                    </span>
                  )}
                </span>
                <span className="block opacity-75 leading-snug mt-1">{description}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* P3 Intelligence toggles */}
      <div className="rounded-xl border border-line px-3 py-2.5 space-y-1.5">
        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
          Intelligence options
        </p>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <Toggle checked={useKnowledgeBase} onChange={setUseKnowledgeBase} disabled={isLoading} />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Knowledge Base</span>
            <span className="text-gray-500 dark:text-gray-400 ml-1">– inject relevant documents into agent prompts</span>
            <a href="/knowledge" className="ml-2 text-blue-500 hover:underline text-xs">Manage docs ↗</a>
          </span>
        </label>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <Toggle checked={enableAgentMemory} onChange={setEnableAgentMemory} disabled={isLoading} />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Agent Memory</span>
            <span className="text-gray-500 dark:text-gray-400 ml-1">— use lessons learned from prior debates</span>
          </span>
        </label>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <Toggle checked={supervised} onChange={setSupervised} disabled={isLoading} />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            <span className="font-medium">Supervised mode</span>
            <span className="text-gray-500 dark:text-gray-400 ml-1">— pause for human review before finalising</span>
          </span>
        </label>
      </div>

      {/* Submit / Cancel — docked to the bottom of the config panel on desktop;
          a normal in-flow button on mobile so it never overlaps the form. */}
      <div className="flex flex-col gap-2 pt-2 bg-surface-raised border-t border-line
                      lg:sticky lg:bottom-0 lg:-mx-5 lg:-mb-5 lg:px-5 lg:py-2.5
                      lg:shadow-[0_-6px_16px_-8px_rgba(0,0,0,0.12)]">
        {!isLoading && query.trim().length < 10 && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Enter a question (10+ characters) to start a debate.
          </p>
        )}
        <div className="flex gap-3">
          <Button
            type="submit"
            variant="primary"
            disabled={isLoading || query.trim().length < 10}
            loading={isLoading}
            className="flex-1 font-semibold"
          >
            {isLoading ? "Agents are debating…" : "Start Debate"}
          </Button>
          {isLoading && onCancel && (
            <Button type="button" variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
