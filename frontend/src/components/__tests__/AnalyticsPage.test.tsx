import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import AnalyticsPage from "@/app/analytics/page";
import type { AnalyticsAgents, AnalyticsConvergence, AnalyticsOverview } from "@/lib/types";

const overview: AnalyticsOverview = {
  total_debates: 4,
  avg_rounds: 2.5,
  avg_rounds_to_consensus: 1.5,
  avg_agreement_score: 0.8,
  debates_by_termination: { consensus_reached: 3, max_rounds_reached: 1 },
  debates_per_day: [],
  trend_days: 7,
};

const stats = { avg_confidence: 0.8, avg_critique_severity_given: {}, avg_contribution_score: 0.5 };
const agents: AnalyticsAgents = {
  agents: { Analyst: stats, Finance: stats, Risk: stats },
  agreement_matrix: {
    Analyst: { Analyst: 1, Finance: null, Risk: 0.42 },
    Finance: { Analyst: null, Finance: 1, Risk: 0.1 },
    Risk: { Analyst: 0.42, Finance: 0.1, Risk: 1 },
  },
};

const convergence: AnalyticsConvergence = {
  avg_agreement_by_round: [],
  mode_breakdown: {},
  domain_pack_breakdown: {},
};

vi.mock("@/lib/api", () => ({
  getAnalyticsOverview: vi.fn(async () => overview),
  getAnalyticsAgents: vi.fn(async () => agents),
  getAnalyticsConvergence: vi.fn(async () => convergence),
  getAnalyticsQuality: vi.fn(async () => null),
  ApiError: class ApiError extends Error {},
}));

beforeAll(() => {
  // recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

describe("AnalyticsPage", () => {
  it("shows overall rounds with the consensus-only average alongside", async () => {
    render(<AnalyticsPage />);
    expect(await screen.findByText("2.5")).toBeTruthy();
    expect(screen.getByText("1.5 when consensus is reached")).toBeTruthy();
  });

  it("labels the trend with the range it covers", async () => {
    render(<AnalyticsPage />);
    expect(await screen.findByText("Debates per day (last 7 days)")).toBeTruthy();
    expect(screen.getByText("No completed debates in the last 7 days.")).toBeTruthy();
  });

  it("shows a dash for agents that never debated together", async () => {
    render(<AnalyticsPage />);
    await screen.findByText("2.5");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    });

    expect(screen.getByText("Pairwise agreement (how alike two agents' final positions were)")).toBeTruthy();
    expect(screen.getAllByTitle("Analyst and Finance have not debated together")).toHaveLength(1);
    expect(screen.getAllByText("42.0%")).toHaveLength(2);
  });
});
