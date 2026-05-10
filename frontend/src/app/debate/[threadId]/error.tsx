"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function DebateError({ error, reset }: ErrorProps) {
  const router = useRouter();

  useEffect(() => {
    console.error("Debate page error:", error);
  }, [error]);

  return (
    <div className="max-w-lg mx-auto py-16 space-y-5 px-4">
      <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-xl p-6 space-y-4">
        <h2 className="text-lg font-semibold text-red-700 dark:text-red-400">
          Debate Error
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {error.message || "An error occurred while loading this debate."}
        </p>
        <div className="flex gap-3">
          <button
            onClick={reset}
            className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition"
          >
            Retry stream
          </button>
          <button
            onClick={() => router.push("/")}
            className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 transition"
          >
            Start new debate
          </button>
        </div>
      </div>
    </div>
  );
}
