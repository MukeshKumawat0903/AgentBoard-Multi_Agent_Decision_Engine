/**
 * LoadingState – spinner + animated stepped progress shown while a debate starts.
 */

"use client";

import { useEffect, useState } from "react";

const STEPS = [
  { label: "Agents proposing…",   icon: "💬" },
  { label: "Agents critiquing…",  icon: "🔍" },
  { label: "Agents revising…",    icon: "✏️" },
  { label: "Converging…",         icon: "🎯" },
];

export default function LoadingState({ message }: { message?: string }) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStepIndex((i) => (i + 1) % STEPS.length);
    }, 2500);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center py-16 gap-6">
      {/* Spinner */}
      <div className="relative w-14 h-14">
        <div className="absolute inset-0 rounded-full border-4 border-gray-200 dark:border-gray-700" />
        <div className="absolute inset-0 rounded-full border-4 border-blue-500 border-t-transparent animate-spin" />
        <span className="absolute inset-0 flex items-center justify-center text-xl">
          {STEPS[stepIndex].icon}
        </span>
      </div>

      {/* Main message */}
      <p className="text-base font-medium text-gray-700 dark:text-gray-300">
        {message ?? STEPS[stepIndex].label}
      </p>

      {/* Step dots */}
      <div className="flex items-center gap-2">
        {STEPS.map((step, i) => (
          <div
            key={step.label}
            className={`flex items-center gap-1.5 text-xs transition-all duration-500 ${
              i === stepIndex
                ? "text-blue-600 dark:text-blue-400 font-medium"
                : i < stepIndex
                ? "text-green-500 line-through opacity-60"
                : "text-gray-400 dark:text-gray-500"
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${
              i === stepIndex ? "bg-blue-500 animate-pulse" :
              i < stepIndex   ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"
            }`} />
            {step.label}
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-400 dark:text-gray-500">
        This may take 30–90 s depending on the query complexity.
      </p>
    </div>
  );
}
