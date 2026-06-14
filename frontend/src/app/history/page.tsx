/**
 * History page – browse and search past completed debates.
 * Route: /history
 */

"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BookOpen, Brain, Check } from "lucide-react";
import type { HistoryItem, HistoryListResponse } from "@/lib/types";
import { getHistory, ApiError } from "@/lib/api";
import { SkeletonList } from "@/components/Skeleton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";

const LIMIT = 15;

type TerminationFilter = "all" | "consensus_reached" | "max_rounds_reached";
type SortOrder = "newest" | "oldest" | "highest_agreement";

export default function HistoryPage() {
  const router = useRouter();
  const [data, setData] = useState<HistoryListResponse | null>(null);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [terminationFilter, setTerminationFilter] = useState<TerminationFilter>("all");
  const [sortOrder, setSortOrder] = useState<SortOrder>("newest");

  const load = useCallback(
    async (p: number, q: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await getHistory({ page: p, limit: LIMIT, q: q || undefined });
        setData(res);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load history.");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    load(page, query);
  }, [page, query, load]);

  // Debounce inputValue → query (300 ms). Resets to page 1 on each new search.
  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      setQuery(inputValue.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [inputValue]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setQuery(inputValue.trim());
  }

  function handleClear() {
    setInputValue("");
    setPage(1);
    setQuery("");
    setTerminationFilter("all");
    setSortOrder("newest");
  }

  const filteredItems = useMemo(() => {
    if (!data) return [];
    let items = [...data.items];
    if (terminationFilter !== "all") {
      items = items.filter((i) => i.termination_reason === terminationFilter);
    }
    if (sortOrder === "oldest") items.sort((a, b) => a.created_at.localeCompare(b.created_at));
    else if (sortOrder === "highest_agreement") items.sort((a, b) => b.agreement_score - a.agreement_score);
    else items.sort((a, b) => b.created_at.localeCompare(a.created_at));
    return items;
  }, [data, terminationFilter, sortOrder]);

  const totalPages = data ? Math.ceil(data.total / LIMIT) : 0;

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fadeIn">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-gray-800 dark:text-gray-100">
          Debate History
        </h1>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
          Browse and search all completed multi-agent debates.
        </p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Search by query or decision…"
          className="flex-1 px-4 py-2 rounded-lg border border-line-strong bg-surface-raised text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
        />
        <Button type="submit" variant="primary" size="sm" className="px-4">
          Search
        </Button>
        {(query || terminationFilter !== "all" || sortOrder !== "newest") && (
          <Button type="button" variant="secondary" size="sm" className="px-4" onClick={handleClear}>
            Reset
          </Button>
        )}
      </form>

      {/* Filter chips + sort */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-400 font-medium">Filter:</span>
        {(["all", "consensus_reached", "max_rounds_reached"] as TerminationFilter[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => { setTerminationFilter(f); setPage(1); }}
            className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium border transition ${
              terminationFilter === f
                ? "bg-accent-600 border-accent-600 text-white"
                : "border-line-strong text-gray-600 dark:text-gray-400 hover:border-accent-400"
            }`}
          >
            {f === "consensus_reached" && <Check className="w-3 h-3" aria-hidden="true" />}
            {f === "all" ? "All" : f === "consensus_reached" ? "Consensus" : "Max Rounds"}
          </button>
        ))}

        <span className="ml-auto flex items-center gap-2 text-xs text-gray-400">
          Sort:
          <select
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value as SortOrder)}
            className="text-xs rounded border border-line-strong bg-surface-raised text-gray-700 dark:text-gray-300 px-2 py-1 focus:outline-none focus:ring-1 focus:ring-accent-500"
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="highest_agreement">Highest agreement</option>
          </select>
        </span>
      </div>

      {/* Results */}
      {error && (
        <div className="flex items-center justify-between gap-4 p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => load(page, query)}
            className="shrink-0 text-xs font-medium underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <SkeletonList count={5} />
      ) : !error && filteredItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 gap-5 text-center">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none" aria-hidden="true">
            <rect width="64" height="64" rx="16" className="fill-gray-100 dark:fill-gray-800" />
            <rect x="16" y="20" width="32" height="4" rx="2" className="fill-gray-300 dark:fill-gray-600" />
            <rect x="16" y="29" width="24" height="3" rx="1.5" className="fill-gray-200 dark:fill-gray-700" />
            <rect x="16" y="36" width="28" height="3" rx="1.5" className="fill-gray-200 dark:fill-gray-700" />
            <rect x="16" y="43" width="20" height="3" rx="1.5" className="fill-gray-200 dark:fill-gray-700" />
          </svg>
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-300 text-base">
              {query || terminationFilter !== "all"
                ? "No debates match the current filters."
                : "No debates yet"}
            </p>
            {!query && terminationFilter === "all" && (
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                Start your first debate to see it here.
              </p>
            )}
          </div>
          {!query && terminationFilter === "all" && (
            <Link
              href="/"
              className="px-5 py-2.5 rounded-lg bg-accent-600 text-white text-sm font-medium hover:bg-accent-700 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
            >
              Start your first debate →
            </Link>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredItems.map((item) => (
            <HistoryCard key={item.thread_id} item={item} router={router} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-sm text-gray-400">
            Page {page} of {totalPages} ({data?.total} total)
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* History Card                                                        */
/* ------------------------------------------------------------------ */

function HistoryCard({
  item,
  router,
}: {
  item: HistoryItem;
  router: ReturnType<typeof useRouter>;
}) {
  const date = new Date(item.created_at);
  const agreementPercent = Math.round(item.agreement_score * 100);
  const barColor =
    agreementPercent >= 75 ? "bg-green-500" :
    agreementPercent >= 50 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div
      className="rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-4
                 hover:-translate-y-0.5 hover:shadow-card-hover transition-all duration-200 cursor-pointer group"
      onClick={() => router.push(`/debate/${item.thread_id}`)}
    >
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-gray-800 dark:text-gray-200 font-medium truncate group-hover:text-accent-600 dark:group-hover:text-accent-400 transition">
            {item.user_query}
          </p>
          <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-gray-400">
            <span>{date.toLocaleDateString()} {date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            <span>{item.total_rounds} round{item.total_rounds !== 1 ? "s" : ""}</span>
            {/* Feature badges — show which enrichments were active */}
            {item.use_knowledge_base && (
              <Badge tone="info">
                <BookOpen className="w-3 h-3" aria-hidden="true" /> KB
              </Badge>
            )}
            {item.enable_agent_memory && (
              <Badge tone="violet">
                <Brain className="w-3 h-3" aria-hidden="true" /> Memory
              </Badge>
            )}
            <Badge tone={item.termination_reason === "consensus_reached" ? "success" : "warning"}>
              {item.termination_reason === "consensus_reached" && (
                <Check className="w-3 h-3" aria-hidden="true" />
              )}
              {item.termination_reason === "consensus_reached" ? "Consensus" : "Max Rounds"}
            </Badge>
          </div>

          {/* Agreement bar */}
          <div className="flex items-center gap-2 mt-2">
            <div className="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${barColor}`}
                style={{ width: `${agreementPercent}%` }}
              />
            </div>
            <span className={`text-xs font-semibold tabular-nums ${
              agreementPercent >= 75 ? "text-green-600 dark:text-green-400" :
              agreementPercent >= 50 ? "text-yellow-600 dark:text-yellow-400" :
              "text-red-500 dark:text-red-400"
            }`}>
              {agreementPercent}% agreement
            </span>
          </div>
        </div>

        {/* Buttons */}
        <div className="flex flex-col gap-1 shrink-0">
          <Button
            size="sm"
            variant="primary"
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/debate/${item.thread_id}`);
            }}
          >
            View
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/compare?a=${item.thread_id}`);
            }}
          >
            Compare
          </Button>
        </div>
      </div>
    </div>
  );
}
