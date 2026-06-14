import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import FinalDecisionPanel from "@/components/FinalDecisionPanel";
import type { FinalDecision } from "@/lib/types";

// Mock API calls so no network I/O during tests
vi.mock("@/lib/api", () => ({
  evaluateDecision: vi.fn(),
  exportDecision: vi.fn(),
}));

// Mock Toast context
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

// Mock DebateTimeline (heavy sub-component with recharts)
vi.mock("@/components/DebateTimeline", () => ({
  default: () => <div data-testid="debate-timeline" />,
}));

function makeDecision(overrides: Partial<FinalDecision> = {}): FinalDecision {
  return {
    thread_id: "thread-001",
    query: "Should we expand?",
    decision: "Proceed with phased rollout.",
    rationale_summary: "Market data and risk analysis support a cautious expansion.",
    confidence_score: 0.85,
    agreement_score: 0.78,
    risk_flags: ["Currency risk", "Regulatory risk"],
    alternatives: ["Delay one quarter", "Partner locally"],
    dissenting_opinions: ["Strategy agent disagreed on timing"],
    debate_trace: [],
    total_rounds: 3,
    termination_reason: "consensus_reached",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  (localStorage.getItem as ReturnType<typeof vi.fn>).mockReturnValue(null);
});

describe("FinalDecisionPanel", () => {
  it("renders decision text prominently", () => {
    render(<FinalDecisionPanel decision={makeDecision()} />);
    expect(screen.getByText("Proceed with phased rollout.")).toBeTruthy();
  });

  it("renders rationale summary", () => {
    render(<FinalDecisionPanel decision={makeDecision()} />);
    expect(screen.getByText(/Market data and risk analysis/)).toBeTruthy();
  });

  it("renders all risk flags", () => {
    render(<FinalDecisionPanel decision={makeDecision()} />);
    expect(screen.getByText("Currency risk")).toBeTruthy();
    expect(screen.getByText("Regulatory risk")).toBeTruthy();
  });

  it("renders alternatives list", () => {
    render(<FinalDecisionPanel decision={makeDecision()} />);
    expect(screen.getByText("Delay one quarter")).toBeTruthy();
    expect(screen.getByText("Partner locally")).toBeTruthy();
  });

  it("renders round count badge", () => {
    render(<FinalDecisionPanel decision={makeDecision({ total_rounds: 3 })} />);
    expect(screen.getByText("3 rounds")).toBeTruthy();
  });

  it("shows termination reason badge", () => {
    render(<FinalDecisionPanel decision={makeDecision({ termination_reason: "max_rounds_reached" })} />);
    expect(screen.getByText(/max rounds reached/i)).toBeTruthy();
  });

  it("hides risk flags section when empty", () => {
    render(<FinalDecisionPanel decision={makeDecision({ risk_flags: [] })} />);
    expect(screen.queryByText("Risk Flags")).toBeNull();
  });

  it("hides alternatives section when empty", () => {
    render(<FinalDecisionPanel decision={makeDecision({ alternatives: [] })} />);
    expect(screen.queryByText("Alternatives Considered")).toBeNull();
  });

  it("renders minority report toggle when entries exist", () => {
    render(<FinalDecisionPanel decision={makeDecision({
      minority_report: [{
        agent_name: "Risk",
        final_position: "Too risky.",
        dissent_reason: "Confidence 0.45 is more than 0.20 below group mean.",
        confidence_score: 0.45,
      }],
    })} />);
    expect(screen.getByText(/Minority Report/)).toBeTruthy();
  });

  it("expands minority report on click", () => {
    render(<FinalDecisionPanel decision={makeDecision({
      minority_report: [{
        agent_name: "Risk",
        final_position: "Too risky.",
        dissent_reason: "Low confidence dissent.",
        confidence_score: 0.45,
      }],
    })} />);
    const toggle = screen.getByText(/Minority Report/);
    fireEvent.click(toggle);
    expect(screen.getByText("Too risky.")).toBeTruthy();
  });

  it("renders key disagreements toggle when entries exist", () => {
    render(<FinalDecisionPanel decision={makeDecision({ key_disagreements: ["Timing is unclear"] })} />);
    expect(screen.getByText(/Key Disagreements/)).toBeTruthy();
  });

  it("renders agent contribution bars when scores provided", () => {
    render(<FinalDecisionPanel decision={makeDecision({
      agent_contribution_scores: { Analyst: 0.8, Risk: 0.6 },
    })} />);
    expect(screen.getByText("Agent Contributions")).toBeTruthy();
    expect(screen.getByText("Analyst")).toBeTruthy();
  });

  it("renders export buttons", () => {
    render(<FinalDecisionPanel decision={makeDecision()} />);
    expect(screen.getAllByText(/Markdown/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/PDF/i).length).toBeGreaterThan(0);
  });

  it("renders Evaluate Quality button", () => {
    render(<FinalDecisionPanel decision={makeDecision()} />);
    expect(screen.getByText(/Evaluate Quality/i)).toBeTruthy();
  });
});
