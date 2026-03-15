/**
 * Home page — the debate input form.
 *
 * Submits the query via the async endpoint, then navigates immediately
 * to the live-streaming debate page.
 */

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import DebateInput from "@/components/DebateInput";
import LoadingState from "@/components/LoadingState";
import { startDebateAsync } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(query: string, maxRounds: number) {
    setIsLoading(true);
    setError(null);
    try {
      const res = await startDebateAsync({ query, max_rounds: maxRounds });
      // Navigate immediately – the debate page streams progress via SSE
      router.push(`/debate/${res.thread_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
      setIsLoading(false);
    }
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

      {/* Input / Loading */}
      {isLoading ? (
        <LoadingState />
      ) : (
          <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
          <DebateInput onSubmit={handleSubmit} isLoading={isLoading} />
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
