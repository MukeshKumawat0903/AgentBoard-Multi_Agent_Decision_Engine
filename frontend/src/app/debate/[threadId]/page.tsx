/**
 * Debate page – streams live events via SSE while the debate runs,
 * then shows the final decision when complete.
 *
 * Route: /debate/[threadId]
 */

"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import DebateStreamViewer from "@/components/DebateStreamViewer";

export default function DebatePage() {
  const params = useParams<{ threadId: string }>();
  const router = useRouter();
  const [query, setQuery] = useState("");

  if (!params.threadId) {
    return null;
  }

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <button
          onClick={() => router.push("/")}
          className="hover:text-gray-600 dark:hover:text-gray-300 transition"
        >
          Home
        </button>
        <span>/</span>
        <span
          className="text-gray-600 dark:text-gray-300 font-medium truncate max-w-xs"
          title={query || params.threadId}
        >
          {query || `Debate ${params.threadId.slice(0, 8)}`}
        </span>
      </div>

      <DebateStreamViewer threadId={params.threadId} onQuery={setQuery} />
    </div>
  );
}
