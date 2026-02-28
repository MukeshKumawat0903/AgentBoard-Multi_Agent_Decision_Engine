/**
 * Debate result page – shows the final decision and full debate trace
 * for a given thread ID.
 *
 * Route: /debate/[threadId]
 *
 * Fetches from GET /decision/{thread_id}.
 */

"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { FinalDecision } from "@/lib/types";
import { getDecision, ApiError } from "@/lib/api";
import FinalDecisionPanel from "@/components/FinalDecisionPanel";
import LoadingState from "@/components/LoadingState";

export default function DebateResultPage() {
  const params = useParams<{ threadId: string }>();
  const router = useRouter();

  const [decision, setDecision] = useState<FinalDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!params.threadId) return;

    let cancelled = false;

    async function load() {
      try {
        const data = await getDecision(params.threadId as string);
        if (!cancelled) setDecision(data);
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError && err.status === 404) {
            setError("Debate not found. It may have expired or the ID is invalid.");
          } else if (err instanceof ApiError && err.status === 409) {
            setError("This debate is still in progress. Please wait.");
          } else {
            setError(
              err instanceof Error ? err.message : "Failed to load debate.",
            );
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [params.threadId]);

  if (loading) {
    return <LoadingState message="Loading decision…" />;
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20 space-y-4">
        <p className="text-red-600 font-medium">{error}</p>
        <button
          onClick={() => router.push("/")}
          className="px-4 py-2 rounded-lg bg-gray-800 text-white text-sm font-medium hover:bg-gray-700 transition"
        >
          Back to Home
        </button>
      </div>
    );
  }

  if (!decision) return null;

  return (
    <div className="space-y-6">
      {/* Breadcrumb / back */}
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <button
          onClick={() => router.push("/")}
          className="hover:text-gray-600 transition"
        >
          Home
        </button>
        <span>/</span>
        <span className="text-gray-600 font-medium truncate">
          {decision.thread_id}
        </span>
      </div>

      {/* Original query */}
      {decision.query && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
          <p className="text-xs text-blue-500 font-medium mb-1">Original Query</p>
          <p className="text-gray-800">{decision.query}</p>
        </div>
      )}

      {/* Decision panel (includes debate trace) */}
      <FinalDecisionPanel decision={decision} />
    </div>
  );
}
