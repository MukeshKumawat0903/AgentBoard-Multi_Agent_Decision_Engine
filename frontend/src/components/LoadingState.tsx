/**
 * LoadingState – spinner + animated "thinking" text shown while a debate runs.
 */

"use client";

export default function LoadingState({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-6">
      {/* Spinner */}
      <div className="relative w-16 h-16">
        <div className="absolute inset-0 rounded-full border-4 border-gray-200 dark:border-gray-700" />
        <div className="absolute inset-0 rounded-full border-4 border-blue-500 border-t-transparent animate-spin" />
      </div>

      {/* Animated text */}
      <div className="text-center space-y-2">
        <p className="text-lg font-medium text-gray-700 dark:text-gray-300">
          {message ?? "Agents are debating\u2026"}
        </p>
        <p className="text-sm text-gray-400 dark:text-gray-500 animate-pulse">
          This may take 30–90 seconds depending on the complexity of the query.
        </p>
      </div>

      {/* Phase indicator dots */}
      <div className="flex items-center gap-3">
        {["Proposals", "Critiques", "Revisions", "Convergence"].map(
          (phase, i) => (
            <span
              key={phase}
              className="text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1"
            >
              <span
                className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse"
                style={{ animationDelay: `${i * 200}ms` }}
              />
              {phase}
            </span>
          )
        )}
      </div>
    </div>
  );
}
