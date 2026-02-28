/**
 * ConfidenceMeter – coloured progress bar for 0-1 score.
 *
 * Colour bands:
 *   0  – 0.3  Red
 *   0.3 – 0.6  Yellow
 *   0.6 – 0.8  Light Green
 *   0.8 – 1.0  Green
 */

"use client";

interface ConfidenceMeterProps {
  score: number;
  label?: string;
  size?: "sm" | "md";
}

function barColor(score: number): string {
  if (score < 0.3) return "bg-red-500";
  if (score < 0.6) return "bg-yellow-400";
  if (score < 0.8) return "bg-lime-400";
  return "bg-green-500";
}

export default function ConfidenceMeter({
  score,
  label,
  size = "md",
}: ConfidenceMeterProps) {
  const pct = Math.round(score * 100);
  const height = size === "sm" ? "h-2" : "h-3";

  return (
    <div className="w-full">
      {label && (
        <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
          <span>{label}</span>
          <span>{pct}%</span>
        </div>
      )}
      <div className={`w-full ${height} rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden`}>
        <div
          className={`${height} rounded-full ${barColor(score)} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
