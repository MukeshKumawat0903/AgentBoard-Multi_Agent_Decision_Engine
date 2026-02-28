/**
 * DebateInput – form for starting a new debate.
 *
 * Contains a textarea (min 10 chars), optional max-rounds slider (2–8),
 * and a submit button with loading state.
 */

"use client";

import { useState, type FormEvent, type ChangeEvent } from "react";

interface DebateInputProps {
  onSubmit: (query: string, maxRounds: number) => void;
  isLoading: boolean;
}

export default function DebateInput({ onSubmit, isLoading }: DebateInputProps) {
  const [query, setQuery] = useState("");
  const [maxRounds, setMaxRounds] = useState(4);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (query.trim().length < 10) return;
    onSubmit(query.trim(), maxRounds);
  }

  const queryTooShort = query.trim().length > 0 && query.trim().length < 10;

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Text area */}
      <div>
        <label
          htmlFor="query"
          className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
        >
          What should the agents debate?
        </label>
        <textarea
          id="query"
          rows={4}
          value={query}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setQuery(e.target.value)}
          placeholder="e.g. Should our company expand into the Asian market in Q3?"
          disabled={isLoading}
          className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-3 text-sm
                     bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                     placeholder:text-gray-400 dark:placeholder:text-gray-500
                     focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                     disabled:bg-gray-50 dark:disabled:bg-gray-700 disabled:text-gray-400 resize-y"
        />
        {queryTooShort && (
          <p className="text-xs text-red-500 mt-1">
            Query must be at least 10 characters.
          </p>
        )}
      </div>

      {/* Max rounds slider */}
      <div>
        <label
          htmlFor="maxRounds"
          className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
        >
          Max rounds: <span className="font-bold">{maxRounds}</span>
        </label>
        <input
          id="maxRounds"
          type="range"
          min={2}
          max={8}
          value={maxRounds}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setMaxRounds(Number(e.target.value))}
          disabled={isLoading}
          className="w-full accent-blue-500"
        />
        <div className="flex justify-between text-[11px] text-gray-400 dark:text-gray-500 px-0.5">
          <span>2</span>
          <span>8</span>
        </div>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={isLoading || query.trim().length < 10}
        className="w-full py-3 rounded-lg bg-blue-600 text-white font-semibold text-sm
                   hover:bg-blue-700 focus:ring-2 focus:ring-blue-400 focus:ring-offset-2
                   disabled:opacity-50 disabled:cursor-not-allowed transition"
      >
        {isLoading ? "Agents are debating…" : "Start Debate"}
      </button>
    </form>
  );
}
