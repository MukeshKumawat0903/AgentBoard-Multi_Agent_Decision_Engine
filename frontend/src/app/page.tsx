/**
 * Home page — the debate input form.
 *
 * Submits the query via the async endpoint, then navigates immediately
 * to the live-streaming debate page.
 */

"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import DebateInput from "@/components/DebateInput";
import type { DebateOptions } from "@/components/DebateInput";
import LoadingState from "@/components/LoadingState";
import TemplateCard from "@/components/TemplateCard";
import { startDebateAsync, getTemplates, getDomainPacks } from "@/lib/api";

import type { DebateMode, DebateTemplate, DomainPack } from "@/lib/types";

export default function HomePage() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [templates, setTemplates] = useState<DebateTemplate[]>([]);
  const [showTemplates, setShowTemplates] = useState(false);
  const [prefillQuery, setPrefillQuery] = useState("");
  const [prefillMode, setPrefillMode] = useState<DebateMode | undefined>();
  const [prefillKey, setPrefillKey] = useState(0);
  const [domainPacks, setDomainPacks] = useState<DomainPack[]>([]);
  const [selectedDomainPack, setSelectedDomainPack] = useState<string | null>(null);

  useEffect(() => {
    getTemplates().then(setTemplates).catch(() => {});
    getDomainPacks().then(setDomainPacks).catch(() => {});
    return () => { abortRef.current?.abort(); };
  }, []);

  async function handleSubmit(query: string, options: DebateOptions) {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setIsLoading(true);
    setError(null);
    try {
      const res = await startDebateAsync(
        {
          query,
          mode: options.mode,
          agents: options.agents,
          use_knowledge_base: options.use_knowledge_base,
          enable_agent_memory: options.enable_agent_memory,
          supervised: options.supervised,
          domain_pack: options.domain_pack ?? selectedDomainPack ?? undefined,
        },
        abortRef.current.signal
      );
      if (!res) return; // aborted
      router.push(`/debate/${res.thread_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
      setIsLoading(false);
    }
  }

  function handleCancel() {
    abortRef.current?.abort();
    setIsLoading(false);
  }

  function handleTemplateSelect(template: DebateTemplate) {
    setPrefillQuery(template.query);
    setPrefillMode(template.mode as DebateMode);
    setPrefillKey((k) => k + 1);
    setShowTemplates(false);
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Hero */}
      <section className="text-center mb-10">
        <h1 className="text-3xl sm:text-4xl font-bold text-gray-800 dark:text-gray-100 mb-3">
          Multi-Agent Decision Engine
        </h1>
        <p className="text-gray-500 dark:text-gray-400 leading-relaxed">
          Submit a strategic question and let five specialised AI agents — an
          Analyst, Risk Assessor, Strategist, Ethics Advisor, and Moderator —
          debate and converge on a well-reasoned decision.
        </p>
      </section>

      {/* Domain pack selector */}
      {!isLoading && domainPacks.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wide">Domain Pack (optional)</p>
          <div className="flex flex-wrap gap-2">
            {domainPacks.map((pack) => {
              const active = selectedDomainPack === pack.id;
              return (
                <button
                  key={pack.id}
                  type="button"
                  onClick={() => setSelectedDomainPack(active ? null : pack.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm transition ${
                    active
                      ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                      : "border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500"
                  }`}
                  title={pack.description}
                >
                  <span>{pack.icon}</span>
                  <span>{pack.name}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Template picker toggle */}
      {!isLoading && templates.length > 0 && (
        <div className="mb-4">
          <button
            type="button"
            onClick={() => setShowTemplates((v) => !v)}
            className="inline-flex items-center gap-2 text-sm font-medium text-blue-600 dark:text-blue-400
                       hover:text-blue-700 dark:hover:text-blue-300 transition"
          >
            <span>{showTemplates ? "▲" : "▼"}</span>
            {showTemplates ? "Hide templates" : "Browse templates"}
            <span className="text-xs bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded-full">
              {templates.length}
            </span>
          </button>

          {showTemplates && (
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {templates.map((t) => (
                <TemplateCard key={t.id} template={t} onSelect={handleTemplateSelect} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Input / Loading */}
      {isLoading ? (
        <LoadingState />
      ) : (
        <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <DebateInput
            key={prefillKey}
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            isLoading={isLoading}
            prefillQuery={prefillQuery}
            prefillMode={prefillMode}
            selectedDomainPack={selectedDomainPack}
          />
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="mt-4 p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Feature cards */}
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-12">
        {[
          {
            icon: "🧠",
            title: "5 Expert Agents",
            desc: "Each agent brings a unique perspective — from market analysis to ethical review.",
          },
          {
            icon: "⚡",
            title: "Structured Debate",
            desc: "Proposals → Cross-examination → Revisions → Consensus in multiple rounds.",
          },
          {
            icon: "🎯",
            title: "Converged Decisions",
            desc: "A moderator synthesises perspectives into a single, justified decision.",
          },
        ].map((f) => (
          <div
            key={f.title}
            className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-5 text-center"
          >
            <span className="text-3xl">{f.icon}</span>
            <h3 className="mt-2 font-semibold text-gray-800 dark:text-gray-200 text-sm">
              {f.title}
            </h3>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{f.desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
