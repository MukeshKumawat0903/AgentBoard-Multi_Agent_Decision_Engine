/**
 * RadialGauge – compact SVG ring gauge for 0–1 scores, with count-up.
 *
 * Colour bands match ConfidenceMeter:
 *   0–0.3 red · 0.3–0.6 yellow · 0.6–0.8 lime · 0.8–1 green
 */

"use client";

import useCountUp from "@/lib/useCountUp";

function gaugeColor(pct: number): string {
  if (pct < 30) return "#EF4444";
  if (pct < 60) return "#EAB308";
  if (pct < 80) return "#84CC16";
  return "#22C55E";
}

export interface RadialGaugeProps {
  /** Score in the 0–1 range. */
  score: number;
  label: string;
  size?: number;
}

export default function RadialGauge({ score, label, size = 72 }: RadialGaugeProps) {
  const target = Math.round(score * 100);
  const pct = Math.round(useCountUp(target));
  const stroke = 7;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;

  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label={`${label}: ${target}%`}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            strokeWidth={stroke}
            className="stroke-gray-200 dark:stroke-gray-700"
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            strokeWidth={stroke}
            strokeLinecap="round"
            stroke={gaugeColor(target)}
            strokeDasharray={c}
            strokeDashoffset={c - (pct / 100) * c}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-sm font-bold tabular-nums text-gray-800 dark:text-gray-100">
          {pct}%
        </span>
      </div>
      <span className="text-[11px] text-gray-500 dark:text-gray-400">{label}</span>
    </div>
  );
}
