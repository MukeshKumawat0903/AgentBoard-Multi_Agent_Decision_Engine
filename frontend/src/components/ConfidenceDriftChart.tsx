/**
 * ConfidenceDriftChart – shows each agent's confidence score over rounds
 * as a line chart, with a dashed horizontal line at the consensus threshold.
 *
 * Data source: `DebateRound.agent_outputs[].confidence_score` per round.
 */

"use client";

import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import type { DebateRound } from "@/lib/types";
import { AGENT_META } from "@/lib/types";

interface ChartProps {
  rounds: DebateRound[];
  consensusThreshold?: number;
}

interface ChartRow {
  round: number;
  [agent: string]: number;
}

export default function ConfidenceDriftChart({
  rounds,
  consensusThreshold = 0.75,
}: ChartProps) {
  // Collect all agent names across rounds — memoised to avoid re-building on every render
  const agentNames = useMemo(
    () =>
      Array.from(
        new Set(rounds.flatMap((r) => r.agent_outputs.map((o) => o.agent_name)))
      ),
    [rounds]
  );

  // Build per-round data rows — memoised alongside agentNames
  const data = useMemo<ChartRow[]>(
    () =>
      rounds.map((round) => {
        const row: ChartRow = { round: round.round_number };
        for (const name of agentNames) {
          const output = round.agent_outputs.find((o) => o.agent_name === name);
          if (output) row[name] = output.confidence_score;
        }
        return row;
      }),
    [rounds, agentNames]
  );

  // Find convergence round (last round if debate is done)
  const convergenceRound =
    rounds.length > 0 ? rounds[rounds.length - 1].round_number : null;

  if (rounds.length === 0) return null;

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="round"
            label={{ value: "Round", position: "insideBottomRight", offset: -4, fontSize: 11 }}
            tick={{ fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fontSize: 11 }}
            tickLine={false}
          />
          <Tooltip
            formatter={(value, name) => [
              typeof value === "number"
                ? `${Math.round(value * 100)}%`
                : String(value),
              String(name),
            ]}
            labelFormatter={(label) => `Round ${label}`}
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />

          {/* Consensus threshold dashed line */}
          <ReferenceLine
            y={consensusThreshold}
            stroke="#94a3b8"
            strokeDasharray="5 3"
            label={{
              value: `Threshold ${Math.round(consensusThreshold * 100)}%`,
              fill: "#94a3b8",
              fontSize: 10,
              position: "insideTopRight",
            }}
          />

          {/* Highlight convergence round */}
          {convergenceRound && (
            <ReferenceLine
              x={convergenceRound}
              stroke="#22c55e"
              strokeDasharray="4 2"
              label={{
                value: "Convergence",
                fill: "#22c55e",
                fontSize: 10,
                position: "insideTopLeft",
              }}
            />
          )}

          {/* One line per agent */}
          {agentNames.map((name) => {
            const meta = AGENT_META[name as keyof typeof AGENT_META];
            return (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={meta?.color ?? "#6b7280"}
                strokeWidth={2}
                dot={{ r: 4, strokeWidth: 2 }}
                activeDot={{ r: 6 }}
                connectNulls
              />
            );
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
