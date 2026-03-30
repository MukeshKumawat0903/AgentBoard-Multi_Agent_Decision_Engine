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
import { startDebateAsync, getTemplates, getDomainPacks, getHistory } from "@/lib/api";
import { useToast } from "@/components/Toast";

import type { DebateMode, DebateTemplate, DomainPack, HistoryItem } from "@/lib/types";

export default function HomePage() {
  const router = useRouter();
  const { showToast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [templates, setTemplates] = useState<DebateTemplate[]>([]);
  const [showTemplates, setShowTemplates] = useState(false);
  const [prefillQuery, setPrefillQuery] = useState("");
  const [prefillMode, setPrefillMode] = useState<DebateMode | undefined>();
  const [prefillKey, setPrefillKey] = useState(0);
  const [domainPacks, setDomainPacks] = useState<DomainPack[]>([]);
  const [selectedDomainPack, setSelectedDomainPack] = useState<string | null>(null);
  const [templateSearch, setTemplateSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState("All");
  const [recentDebates, setRecentDebates] = useState<HistoryItem[]>([]);

  useEffect(() => {
    getTemplates().then(setTemplates).catch(() => {});
    getDomainPacks().then(setDomainPacks).catch(() => {});
    getHistory({ page: 1, limit: 3 }).then((r) => setRecentDebates(r.items)).catch(() => {});
    return () => { abortRef.current?.abort(); };
  }, []);

  // Derived: category list and filtered templates
  const templateCategories = ["All", ...Array.from(new Set(templates.map((t) => t.category)))];
  const filteredTemplates = templates
    .filter((t) => activeCategory === "All" || t.category === activeCategory)
    .filter(
      (t) =>
        !templateSearch ||
        t.title.toLowerCase().includes(templateSearch.toLowerCase()) ||
        t.query.toLowerCase().includes(templateSearch.toLowerCase()),
    );

  async function handleSubmit(query: string, options: DebateOptions) {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setIsLoading(true);
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
      showToast(err instanceof Error ? err.message : "An unexpected error occurred.", "error");
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
    setTemplateSearch("");
    setActiveCategory("All");
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Hero */}
      <section className="text-center mb-10 relative py-6 rounded-2xl overflow-hidden">
        {/* Subtle gradient background */}
        <div
          className="absolute inset-0 -z-10 bg-gradient-to-br from-blue-50 via-violet-50/60 to-transparent dark:from-blue-950/20 dark:via-violet-950/10 dark:to-transparent rounded-2xl"
          aria-hidden="true"
        />
        <h1 className="text-3xl sm:text-4xl font-bold mb-3 bg-gradient-to-r from-blue-600 via-violet-500 to-blue-500 dark:from-blue-400 dark:via-violet-400 dark:to-blue-300 bg-clip-text text-transparent">
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
                >
                  <span>{pack.icon}</span>
                  <span>{pack.name}</span>
                </button>
              );
            })}
          </div>
          {/* Inline description of selected domain pack */}
          {selectedDomainPack && (() => {
            const pack = domainPacks.find((p) => p.id === selectedDomainPack);
            return pack ? (
              <p className="mt-2 text-sm text-blue-700 dark:text-blue-300 line-clamp-1 sm:line-clamp-2 leading-relaxed">
                {pack.description}
              </p>
            ) : null;
          })()}
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
            <div className="mt-3 space-y-3">
              {/* Search bar */}
              <input
                type="search"
                placeholder="Search templates…"
                value={templateSearch}
                onChange={(e) => setTemplateSearch(e.target.value)}
                className="w-full text-sm px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700
                           bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 placeholder:text-gray-400
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              {/* Category tabs */}
              <div className="flex flex-wrap gap-1.5">
                {templateCategories.map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setActiveCategory(cat)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition ${
                      activeCategory === cat
                        ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                        : "border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500"
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
              {/* Template grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredTemplates.length > 0 ? (
                  filteredTemplates.map((t) => (
                    <TemplateCard key={t.id} template={t} onSelect={handleTemplateSelect} />
                  ))
                ) : (
                  <p className="col-span-full text-sm text-center text-gray-400 py-6">
                    No templates match your search.
                  </p>
                )}
              </div>
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

      {/* Recent debates quick-access */}
      {!isLoading && recentDebates.length > 0 && (
        <div className="mt-5">
          <p className="text-xs font-medium text-gray-400 dark:text-gray-500 mb-2 uppercase tracking-wide">Recent Debates</p>
          <div className="space-y-2">
            {recentDebates.map((item) => (
              <a
                key={item.thread_id}
                href={`/debate/${item.thread_id}`}
                className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border border-gray-200 dark:border-gray-800
                           bg-white dark:bg-gray-900 hover:border-blue-400 dark:hover:border-blue-600 transition group"
              >
                <span className="text-sm text-gray-700 dark:text-gray-300 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">
                  {item.user_query}
                </span>
                <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">
                  {Math.round(item.agreement_score * 100)}% agree
                </span>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Feature cards */}
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-12">
        {[
          {
            icon: "🧠",
            title: "5 Expert Agents",
            desc: "Each agent brings a unique perspective — from market analysis to ethical review.",
            gradient: "bg-gradient-to-br from-blue-50 to-violet-50 dark:from-blue-950/30 dark:to-violet-950/20",
          },
          {
            icon: "⚡",
            title: "Structured Debate",
            desc: "Proposals → Cross-examination → Revisions → Consensus in multiple rounds.",
            gradient: "bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-950/30 dark:to-orange-950/20",
          },
          {
            icon: "🎯",
            title: "Converged Decisions",
            desc: "A moderator synthesises perspectives into a single, justified decision.",
            gradient: "bg-gradient-to-br from-green-50 to-emerald-50 dark:from-green-950/30 dark:to-emerald-950/20",
          },
        ].map((f) => (
          <div
            key={f.title}
            className="group relative overflow-hidden bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-5 text-center transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md cursor-default"
          >
            <div className={`absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200 ${f.gradient}`} aria-hidden="true" />
            <span className="relative text-3xl">{f.icon}</span>
            <h3 className="relative mt-2 font-semibold text-gray-800 dark:text-gray-200 text-sm">
              {f.title}
            </h3>
            <p className="relative mt-1 text-xs text-gray-500 dark:text-gray-400">{f.desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
