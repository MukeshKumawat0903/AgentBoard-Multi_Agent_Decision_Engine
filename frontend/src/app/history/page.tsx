/**
 * History page – browse and search past completed debates.
 * Route: /history
 */

"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { HistoryItem, HistoryListResponse } from "@/lib/types";
import { getHistory, ApiError } from "@/lib/api";

const LIMIT = 15;

export default function HistoryPage() {
  const router = useRouter();
  const [data, setData] = useState<HistoryListResponse | null>(null);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setQuery(inputValue.trim());
  }

  function handleClear() {
    setInputValue("");
    setPage(1);
    setQuery("");
  }

  const totalPages = data ? Math.ceil(data.total / LIMIT) : 0;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">
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
          className="flex-1 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition"
        >
          Search
        </button>
        {query && (
          <button
            type="button"
            onClick={handleClear}
            className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 transition"
          >
            Clear
          </button>
        )}
      </form>

      {/* Results */}
      {error && (
        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-6 h-6 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data && data.items.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          {query ? `No debates found for "${query}".` : "No completed debates yet."}
        </div>
      ) : (
        <div className="space-y-3">
          {data?.items.map((item) => (
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
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
            >
              Previous
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
            >
              Next
            </button>
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

  return (
    <div
      className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 p-4 hover:shadow-md transition cursor-pointer group"
      onClick={() => router.push(`/debate/${item.thread_id}`)}
    >
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-gray-800 dark:text-gray-200 font-medium truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">
            {item.user_query}
          </p>
          <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-gray-400">
            <span>{date.toLocaleDateString()} {date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            <span>{item.total_rounds} rounds</span>
            <span
              className={`px-2 py-0.5 rounded-full font-medium ${
                item.termination_reason === "consensus_reached"
                  ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400"
                  : "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400"
              }`}
            >
              {item.termination_reason.replace(/_/g, " ")}
            </span>
          </div>
        </div>

        {/* Agreement gauge */}
        <div className="flex flex-col items-center shrink-0">
          <span
            className={`text-xl font-bold tabular-nums ${
              agreementPercent >= 75
                ? "text-green-600 dark:text-green-400"
                : agreementPercent >= 50
                ? "text-yellow-600 dark:text-yellow-400"
                : "text-red-500 dark:text-red-400"
            }`}
          >
            {agreementPercent}%
          </span>
          <span className="text-xs text-gray-400">agreement</span>
        </div>

        {/* Buttons */}
        <div className="flex flex-col gap-1 shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/debate/${item.thread_id}`);
            }}
            className="px-3 py-1 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 transition"
          >
            View
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/compare?a=${item.thread_id}`);
            }}
            className="px-3 py-1 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-xs font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition"
          >
            Compare
          </button>
        </div>
      </div>
    </div>
  );
}
