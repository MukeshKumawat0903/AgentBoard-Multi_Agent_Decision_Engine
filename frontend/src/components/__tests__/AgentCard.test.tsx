import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import AgentCard from "@/components/AgentCard";
import type { AgentResponse } from "@/lib/types";

function makeResponse(overrides: Partial<AgentResponse> = {}): AgentResponse {
  return {
    agent_name: "Analyst",
    round_number: 1,
    position: "Proceed with phased expansion.",
    reasoning: "Market data supports this.",
    assumptions: ["Stable macro", "Currency hedged"],
    confidence_score: 0.82,
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

describe("AgentCard", () => {
  it("renders agent name and round number", () => {
    render(<AgentCard response={makeResponse()} />);
    expect(screen.getByText("Analyst")).toBeTruthy();
    expect(screen.getByText("Round 1")).toBeTruthy();
  });

  it("renders position text", () => {
    render(<AgentCard response={makeResponse({ position: "Do not expand." })} />);
    expect(screen.getByText("Do not expand.")).toBeTruthy();
  });

  it("renders reasoning text", () => {
    render(<AgentCard response={makeResponse({ reasoning: "Risks too high." })} />);
    expect(screen.getByText("Risks too high.")).toBeTruthy();
  });

  it("renders assumptions list when present", () => {
    render(<AgentCard response={makeResponse({ assumptions: ["Assumption A", "Assumption B"] })} />);
    expect(screen.getByText("Assumption A")).toBeTruthy();
    expect(screen.getByText("Assumption B")).toBeTruthy();
  });

  it("hides assumptions section when list is empty", () => {
    render(<AgentCard response={makeResponse({ assumptions: [] })} />);
    expect(screen.queryByText("Assumptions")).toBeNull();
  });

  it("renders confidence meter (score shown as %)", () => {
    render(<AgentCard response={makeResponse({ confidence_score: 0.82 })} />);
    expect(screen.getByText("82%")).toBeTruthy();
  });

  it("renders domain agent (FinancialEthics) without crashing", () => {
    render(<AgentCard response={makeResponse({ agent_name: "FinancialEthics" })} />);
    expect(screen.getByText("FinancialEthics")).toBeTruthy();
  });

  it("uses fallback grey styling for unknown agents", () => {
    const { container } = render(
      <AgentCard response={makeResponse({ agent_name: "UnknownAgent" })} />
    );
    const card = container.firstChild as HTMLElement;
    expect(card.style.borderColor).toBe("rgb(107, 114, 128)"); // #6B7280
  });
});
