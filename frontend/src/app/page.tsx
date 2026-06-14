/**
 * Home page — the New Debate workspace.
 *
 * Two-pane layout: the left column is the configuration form (question, mode,
 * intelligence options, Start); the right rail is context (domain pack →
 * agent roster → recent debates). Submits via the async endpoint, then
 * navigates immediately to the live-streaming debate page.
 */

"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import DebateInput from "@/components/DebateInput";
import type { DebateOptions } from "@/components/DebateInput";
import AgentRoster, { type AgentOption } from "@/components/AgentRoster";
import LoadingState from "@/components/LoadingState";
import TemplateCard from "@/components/TemplateCard";
import { startDebateAsync, getTemplates, getDomainPacks, getHistory, getAgents } from "@/lib/api";
import { useToast } from "@/components/Toast";

import type { DebateMode, DebateTemplate, DomainPack, HistoryItem } from "@/lib/types";

const DEFAULT_AGENTS: AgentOption[] = [
  { name: "Analyst",   icon: "📊", role: "Objective data analyst" },
  { name: "Risk",      icon: "⚠️", role: "Adversarial risk assessor" },
  { name: "Strategy",  icon: "🎯", role: "Actionable strategy proposer" },
  { name: "Ethics",    icon: "⚖️", role: "Ethics and compliance guardian" },
  { name: "Moderator", icon: "🏛️", role: "Neutral synthesizer" },
];

/** Compact relative timestamp, e.g. "3h ago" — disambiguates similar debates. */
function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}

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

  // Participating-agent roster — lifted here so the left config form and the
  // right-rail AgentRoster share one source of truth.
  const [agents, setAgents] = useState<AgentOption[]>(DEFAULT_AGENTS);
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(
    () => new Set(DEFAULT_AGENTS.map((a) => a.name)),
  );

  useEffect(() => {
    getTemplates().then(setTemplates).catch(() => {});
    getDomainPacks().then(setDomainPacks).catch(() => {});
    getHistory({ page: 1, limit: 3 }).then((r) => setRecentDebates(r.items)).catch(() => {});
    getAgents()
      .then((res) => {
        // Only the enabled core agents are individually selectable; domain
        // experts are activated via a domain pack, not picked one-by-one.
        const core = res.filter((a) => a.enabled);
        if (core.length > 0) {
          setAgents(core.map((a) => ({ name: a.name, icon: a.icon, role: a.role })));
          setSelectedAgents(new Set(core.map((a) => a.name)));
        }
      })
      .catch(() => {});
    return () => { abortRef.current?.abort(); };
  }, []);

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
    <div className="max-w-7xl mx-auto">
      {/* Compact header — title and the templates toggle share one row */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mb-4">
        <h1 className="text-lg sm:text-xl font-bold bg-gradient-to-r from-blue-600 via-violet-500 to-blue-500 dark:from-blue-400 dark:via-violet-400 dark:to-blue-300 bg-clip-text text-transparent">
          Multi-Agent Decision Engine
        </h1>
        {!isLoading && templates.length > 0 && (
          <button
            type="button"
            onClick={() => setShowTemplates((v) => !v)}
            className="shrink-0 inline-flex items-center gap-2 text-sm font-medium text-blue-600 dark:text-blue-400
                       hover:text-blue-700 dark:hover:text-blue-300 transition"
          >
            <span>{showTemplates ? "▲" : "▼"}</span>
            {showTemplates ? "Hide templates" : "Browse templates"}
            <span className="text-xs bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded-full">
              {templates.length}
            </span>
          </button>
        )}
      </div>

      {/* Template picker (expanded) */}
      {!isLoading && templates.length > 0 && showTemplates && (
        <div className="mb-5">
            <div className="space-y-3">
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
        </div>
      )}

      {/* Workspace */}
      {isLoading ? (
        <LoadingState />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-6 items-start">
          {/* LEFT — configuration */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
            <DebateInput
              key={prefillKey}
              onSubmit={handleSubmit}
              onCancel={handleCancel}
              isLoading={isLoading}
              agents={agents}
              selectedAgents={selectedAgents}
              prefillQuery={prefillQuery}
              prefillMode={prefillMode}
              selectedDomainPack={selectedDomainPack}
            />
          </div>

          {/* RIGHT — context rail */}
          <aside className="lg:sticky lg:top-20 space-y-4">
            {/* Domain pack selector — controls the agent roster below it */}
            {domainPacks.length > 0 && (
              <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                  Domain pack <span className="font-normal normal-case">(optional)</span>
                </p>
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
                {selectedDomainPack && (() => {
                  const pack = domainPacks.find((p) => p.id === selectedDomainPack);
                  return pack ? (
                    <p className="mt-2 text-sm text-blue-700 dark:text-blue-300 leading-relaxed">
                      {pack.description}
                    </p>
                  ) : null;
                })()}
              </div>
            )}

            {/* Agent roster */}
            <AgentRoster
              agents={agents}
              selectedAgents={selectedAgents}
              onToggle={toggleAgent}
              selectedDomainPack={selectedDomainPack}
              domainPacks={domainPacks}
            />

            {/* Recent debates quick-access */}
            <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                Recent debates
              </p>
              {recentDebates.length > 0 ? (
                <div className="space-y-2.5">
                  {recentDebates.map((item) => (
                    <a
                      key={item.thread_id}
                      href={`/debate/${item.thread_id}`}
                      className="block px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-800
                                 hover:border-blue-400 dark:hover:border-blue-600 transition group"
                    >
                      <span className="block text-sm text-gray-700 dark:text-gray-300 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">
                        {item.user_query}
                      </span>
                      <span className="mt-1.5 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                        <span>{timeAgo(item.created_at)}</span>
                        <span>{Math.round(item.agreement_score * 100)}% agree</span>
                      </span>
                    </a>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
                  No debates yet. Start your first debate to build history.
                </p>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
