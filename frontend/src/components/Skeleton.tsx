/**
 * Skeleton – loading placeholder components.
 *
 * Use these to replace spinners with content-shaped placeholders.
 *
 * Exports:
 *   SkeletonBlock   – basic rectangle pulse
 *   SkeletonText    – one or more text line pulses
 *   SkeletonCard    – card-shaped skeleton (header + lines)
 *   SkeletonKpi     – KPI card skeleton (label + big number)
 *   SkeletonList    – vertical list of SkeletonCards
 *   SkeletonChart   – chart area placeholder
 */

const base =
  "animate-pulse rounded bg-gray-200 dark:bg-gray-700";

/* ------------------------------------------------------------------ */
/* Primitives                                                          */
/* ------------------------------------------------------------------ */

export function SkeletonBlock({
  className = "",
}: {
  className?: string;
}) {
  return <div aria-hidden="true" className={`${base} ${className}`} />;
}

export function SkeletonText({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div aria-hidden="true" className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`${base} h-3 ${i === lines - 1 && lines > 1 ? "w-4/5" : "w-full"}`}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Composed skeletons                                                  */
/* ------------------------------------------------------------------ */

/** Mimics a rounded card with a header bar and lines of body text. */
export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-4 space-y-3 ${className}`}
    >
      {/* header */}
      <div className="flex items-center gap-3">
        <SkeletonBlock className="h-8 w-8 rounded-full" />
        <div className="flex-1 space-y-1.5">
          <SkeletonBlock className="h-3 w-1/2" />
          <SkeletonBlock className="h-2 w-1/3" />
        </div>
      </div>
      {/* body lines */}
      <SkeletonText lines={3} />
      {/* progress bar stub */}
      <SkeletonBlock className="h-1.5 w-full" />
    </div>
  );
}

/** Mimics a KPI card (label + big number). */
export function SkeletonKpi({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card p-5 space-y-2 ${className}`}
    >
      <SkeletonBlock className="h-3 w-2/3" />
      <SkeletonBlock className="h-8 w-1/2" />
      <SkeletonBlock className="h-2 w-1/3" />
    </div>
  );
}

/** Chart area placeholder. */
export function SkeletonChart({ height = 220, className = "" }: { height?: number; className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`rounded-lg overflow-hidden ${className}`}
      style={{ height }}
    >
      <div className={`${base} h-full w-full`} />
    </div>
  );
}

/** A vertical stack of N skeleton cards, use for list pages. */
export function SkeletonList({
  count = 5,
  className = "",
}: {
  count?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-3 ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

/** Agent-panel skeleton (icon + header + short text). */
export function SkeletonAgentPanel({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card overflow-hidden ${className}`}
    >
      {/* header strip */}
      <div className={`${base} h-14 w-full rounded-none`} />
      <div className="p-4 space-y-3">
        <SkeletonText lines={4} />
      </div>
    </div>
  );
}
