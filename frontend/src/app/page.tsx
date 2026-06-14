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
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown, LayoutGrid } from "lucide-react";
import DebateInput from "@/components/DebateInput";
import type { DebateOptions, SampleQuestion } from "@/components/DebateInput";
import AgentRoster, { type AgentOption } from "@/components/AgentRoster";
import LoadingState from "@/components/LoadingState";
import TemplateCard from "@/components/TemplateCard";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
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

/** Fallback starter questions when no templates are available. */
const FALLBACK_SAMPLES: SampleQuestion[] = [
  { label: "4-day work week?", query: "Should our startup adopt a 4-day work week without cutting salaries?" },
  { label: "Monolith → microservices?", query: "Is it worth migrating our monolith to microservices this year, given a team of 12 engineers?" },
  { label: "Expand to Europe?", query: "Should we expand into the European market next quarter or double down on our home market?" },
  { label: "AI for support?", query: "Should we replace tier-1 customer support with an AI agent while keeping humans for escalations?" },
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

/**
 * Retry a fetch with exponential backoff before giving up.
 * Covers the cold-start window where the Next.js dev proxy can't yet
 * reach the FastAPI backend — a cold uvicorn process with heavy ML
 * imports (langchain/langgraph), or a free-tier hosted backend, can take
 * the better part of a minute to come up. A fixed ~10s window gave up too
 * early, leaving the right-rail boxes hidden until a manual refresh.
 *
 * Delays grow 1s → 2s → 4s → 8s → 10s (capped), so 11 attempts span ~75s
 * while making far fewer calls than polling once a second. Once the backend
 * answers, the rail populates on its own — no refresh needed.
 */
function withRetry<T>(fn: () => Promise<T>, retries = 10, delayMs = 1000): Promise<T> {
  return fn().catch((err) => {
    if (retries <= 0) throw err;
    return new Promise<T>((resolve, reject) => {
      setTimeout(() => {
        const nextDelay = Math.min(delayMs * 2, 10_000);
        withRetry(fn, retries - 1, nextDelay).then(resolve, reject);
      }, delayMs);
    });
  });
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
  // Distinguishes "confirmed empty" from "fetch failed" — we only claim
  // "no debates yet" when the backend actually said so.
  const [recentLoaded, setRecentLoaded] = useState(false);

  // Participating-agent roster — lifted here so the left config form and the
  // right-rail AgentRoster share one source of truth.
  const [agents, setAgents] = useState<AgentOption[]>(DEFAULT_AGENTS);
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(
    () => new Set(DEFAULT_AGENTS.map((a) => a.name)),
  );

  useEffect(() => {
    // On first dev-server load the backend proxy may briefly fail while both
    // servers are still warming up — retry a couple of times before giving up,
    // so the right-rail boxes don't disappear until a manual refresh.
    withRetry(() => getTemplates()).then(setTemplates).catch(() => {});
    withRetry(() => getDomainPacks()).then(setDomainPacks).catch(() => {});
    withRetry(() => getHistory({ page: 1, limit: 3 }))
      .then((r) => {
        setRecentDebates(r.items);
        setRecentLoaded(true);
      })
      .catch(() => {});
    withRetry(() => getAgents())
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
          max_rounds: options.max_rounds,
          consensus_threshold: options.consensus_threshold,
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

  // Starter chips: prefer real templates (title → query), fall back to built-ins.
  const sampleQuestions: SampleQuestion[] =
    templates.length >= 3
      ? templates.slice(0, 4).map((t) => ({ label: t.title, query: t.query }))
      : FALLBACK_SAMPLES;

  return (
    <div className="lg:h-[calc(100dvh-6rem)] lg:flex lg:flex-col lg:overflow-hidden">
      {/* Compact header — templates toggle shares the row so the form stays above the fold */}
      <header className="mb-3 lg:mb-2 lg:flex-none flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-gray-900 dark:text-gray-50">
            Five AI agents.{" "}
            <span className="bg-gradient-to-r from-accent-600 via-violet-500 to-accent-500 dark:from-accent-400 dark:via-violet-400 dark:to-accent-300 bg-clip-text text-transparent">
              One decision.
            </span>
          </h1>
          <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
            Ask anything consequential — the panel debates, critiques and converges
            on a recommendation you can defend.
          </p>
        </div>
        {!isLoading && templates.length > 0 && (
          <button
            type="button"
            onClick={() => setShowTemplates((v) => !v)}
            aria-expanded={showTemplates}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-600 dark:text-accent-400
                       hover:text-accent-700 dark:hover:text-accent-300 transition
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 rounded px-1 py-0.5"
          >
            <LayoutGrid className="w-4 h-4" aria-hidden="true" />
            Templates
            <Badge tone="info">{templates.length}</Badge>
            <ChevronDown
              className={`w-4 h-4 transition-transform duration-200 ${showTemplates ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
          </button>
        )}
      </header>

      {/* Template gallery — animated slide-down panel */}
      {!isLoading && templates.length > 0 && (
        <div
          className={`grid lg:flex-none transition-[grid-template-rows] duration-300 ease-out ${
            showTemplates ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
          }`}
        >
          <div className="overflow-hidden min-h-0">
            <div className="space-y-3 pb-4 lg:max-h-[40vh] lg:overflow-y-auto custom-scroll lg:pr-1">
              {/* Search bar */}
              <input
                type="search"
                placeholder="Search templates…"
                value={templateSearch}
                onChange={(e) => setTemplateSearch(e.target.value)}
                className="w-full text-sm px-3 py-1.5 rounded-lg border border-line
                           bg-surface-raised text-gray-700 dark:text-gray-300 placeholder:text-gray-400
                           focus:outline-none focus:ring-2 focus:ring-accent-500"
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
                        ? "border-accent-500 bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-300"
                        : "border-line text-gray-500 dark:text-gray-400 hover:border-line-strong"
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
        </div>
      )}

      {/* Workspace */}
      {isLoading ? (
        <LoadingState />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-6 items-start lg:items-stretch lg:min-h-0">
          {/* LEFT — configuration (stretches to match the right rail; submit docks at the bottom) */}
          <Card padded={false} className="p-5 lg:min-h-0 lg:overflow-y-auto custom-scroll lg:flex lg:flex-col">
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
              samples={sampleQuestions}
            />
          </Card>

          {/* RIGHT — context rail */}
          <aside className="lg:overflow-y-auto custom-scroll lg:min-h-0 lg:pr-1 space-y-4">
            {/* Agents (domain pack selector + roster in one card) */}
            <AgentRoster
              agents={agents}
              selectedAgents={selectedAgents}
              onToggle={toggleAgent}
              selectedDomainPack={selectedDomainPack}
              domainPacks={domainPacks}
              onSelectDomainPack={setSelectedDomainPack}
            />

            {/* Recent debates quick-access — hidden entirely if the fetch failed */}
            {(recentDebates.length > 0 || recentLoaded) && (
              <Card padded={false} className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    Recent debates
                  </p>
                  {recentDebates.length > 0 && (
                    <Link
                      href="/history"
                      className="text-xs font-medium text-accent-600 dark:text-accent-400
                                 hover:text-accent-700 dark:hover:text-accent-300 transition"
                    >
                      View all →
                    </Link>
                  )}
                </div>
                {recentDebates.length > 0 ? (
                  <div className="-mx-1.5 space-y-0.5">
                    {recentDebates.map((item) => {
                      const pct = Number.isFinite(item.agreement_score)
                        ? Math.round(item.agreement_score * 100)
                        : null;
                      return (
                        <Link
                          key={item.thread_id}
                          href={`/debate/${item.thread_id}`}
                          title={item.user_query}
                          className="flex items-center gap-2 px-1.5 py-1.5 rounded-md
                                     hover:bg-surface transition group"
                        >
                          <span className="flex-1 min-w-0 truncate text-sm text-gray-700 dark:text-gray-300 group-hover:text-accent-600 dark:group-hover:text-accent-400 transition">
                            {item.user_query}
                          </span>
                          <span className="shrink-0 text-[11px] text-gray-400 dark:text-gray-500 tabular-nums">
                            {timeAgo(item.created_at)}
                          </span>
                          {pct !== null && (
                            <span
                              title={`${pct}% agreement`}
                              className={`shrink-0 text-[11px] font-semibold tabular-nums ${
                                pct >= 75
                                  ? "text-green-600 dark:text-green-400"
                                  : pct >= 50
                                  ? "text-yellow-600 dark:text-yellow-400"
                                  : "text-red-500 dark:text-red-400"
                              }`}
                            >
                              {pct}%
                            </span>
                          )}
                        </Link>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
                    No debates yet. Start your first debate to build history.
                  </p>
                )}
              </Card>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
