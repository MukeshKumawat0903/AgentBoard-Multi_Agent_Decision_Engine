"use client";

import { useEffect } from "react";
import Link from "next/link";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: ErrorProps) {
  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  return (
    <div className="max-w-lg mx-auto text-center py-24 space-y-6 px-4">
      <div className="text-5xl">⚠️</div>
      <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">
        Something went wrong
      </h1>
      <p className="text-gray-500 dark:text-gray-400 text-sm">
        {error.message || "An unexpected error occurred. Please try again."}
      </p>
      <div className="flex items-center justify-center gap-3">
        <button
          onClick={reset}
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition"
        >
          Try again
        </button>
        <Link
          href="/"
          className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 transition"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
