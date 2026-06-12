/**
 * LoadingState – brief spinner shown while a debate is being created.
 *
 * The app navigates to the live debate page as soon as the backend accepts
 * the request, so this state lasts a moment — no fake progress steps. Real
 * per-agent progress is rendered by DebateStreamViewer once streaming starts.
 */

"use client";

import { Loader2 } from "lucide-react";

export default function LoadingState({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4" role="status">
      <Loader2 className="w-10 h-10 text-accent-500 animate-spin" aria-hidden="true" />
      <p className="text-base font-medium text-gray-700 dark:text-gray-300">
        {message ?? "Setting up the debate room…"}
      </p>
      <p className="text-xs text-gray-400 dark:text-gray-500">
        You&apos;ll be taken to the live debate in a moment.
      </p>
    </div>
  );
}
