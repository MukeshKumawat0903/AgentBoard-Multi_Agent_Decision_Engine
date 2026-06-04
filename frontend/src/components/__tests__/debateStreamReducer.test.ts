/**
 * Unit tests for debateStreamReducer — pure function, no DOM or React needed.
 * Covers B1 (critique dedup), B4 (dynamic agent status), B5 (termination reason),
 * B6 (agent_timeout), and general event handling correctness.
 */

import { describe, it, expect } from "vitest";
import {
  debateStreamReducer,
  initialStreamState,
  type StreamState,
} from "@/lib/debateStreamReducer";

// ── helpers ────────────────────────────────────────────────────────────────

function stateWith(overrides: Partial<StreamState>): StreamState {
  return { ...initialStreamState, ...overrides };
}

function agentOutputEvent(name: string, round = 1, confidence = 0.8) {
  return {
    type: "agent_output" as const,
    round_number: round,
    phase: "proposal" as const,
    agent_name: name,
    position: `${name} position`,
    reasoning: `${name} reasoning`,
    assumptions: [],
    confidence_score: confidence,
  };
}

function critiqueEvent(critic: string, target: string, round = 1) {
  return {
    type: "critique_completed" as const,
    round_number: round,
    critic_agent: critic,
    target_agent: target,
    severity: "medium" as const,
    critique_points: ["Point A"],
    confidence_score: 0.7,
  };
}

// ── stream_error / clear_approval ─────────────────────────────────────────

describe("meta actions", () => {
  it("stream_error sets status=error and message", () => {
    const next = debateStreamReducer(initialStreamState, { type: "stream_error" });
    expect(next.status).toBe("error");
    expect(next.error).toBe("Stream connection lost.");
  });

  it("clear_approval removes approvalRequired", () => {
    const state = stateWith({ approvalRequired: { type: "approval_required", round_number: 1, agreement_score: 0.7, termination_reason: "consensus_reached", synthesis_summary: "", options: [] } });
    const next = debateStreamReducer(state, { type: "clear_approval" });
    expect(next.approvalRequired).toBeNull();
  });
});

// ── debate_started ─────────────────────────────────────────────────────────

describe("debate_started", () => {
  it("sets query, maxRounds, and streaming status", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: { type: "debate_started", thread_id: "t1", user_query: "Should we expand?", max_rounds: 4 },
    });
    expect(next.status).toBe("streaming");
    expect(next.query).toBe("Should we expand?");
    expect(next.maxRounds).toBe(4);
  });
});

// ── round_started ──────────────────────────────────────────────────────────

describe("round_started (B4)", () => {
  it("resets agentStatus to empty (no AGENT_META pre-seeding)", () => {
    const state = stateWith({ agentStatus: { Analyst: "done", Risk: "done" } });
    const next = debateStreamReducer(state, {
      event: { type: "round_started", round_number: 2, max_rounds: 4 },
    });
    expect(next.agentStatus).toEqual({});
  });

  it("creates a new round entry", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: { type: "round_started", round_number: 1, max_rounds: 4 },
    });
    expect(next.rounds).toHaveLength(1);
    expect(next.rounds[0].round_number).toBe(1);
  });

  it("does not duplicate an existing round", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "critique", agent_outputs: [], critiques: [] }],
    });
    const next = debateStreamReducer(state, {
      event: { type: "round_started", round_number: 1, max_rounds: 4 },
    });
    expect(next.rounds).toHaveLength(1);
  });
});

// ── phase_started ──────────────────────────────────────────────────────────

describe("phase_started (B4)", () => {
  it("marks seen agents as working on phase transition", () => {
    const state = stateWith({
      rounds: [{
        round_number: 1,
        phase: "proposal",
        agent_outputs: [
          { agent_name: "Analyst", round_number: 1, position: "p", reasoning: "r", assumptions: [], confidence_score: 0.8, timestamp: "" },
          { agent_name: "FinancialEthics", round_number: 1, position: "p", reasoning: "r", assumptions: [], confidence_score: 0.7, timestamp: "" },
        ],
        critiques: [],
      }],
    });
    const next = debateStreamReducer(state, {
      event: { type: "phase_started", round_number: 1, phase: "critique" },
    });
    expect(next.agentStatus["Analyst"]).toBe("working");
    expect(next.agentStatus["FinancialEthics"]).toBe("working");
  });

  it("keeps existing agentStatus when no agents seen yet (round 1 start)", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "proposal", agent_outputs: [], critiques: [] }],
      agentStatus: {},
    });
    const next = debateStreamReducer(state, {
      event: { type: "phase_started", round_number: 1, phase: "proposal" },
    });
    expect(next.agentStatus).toEqual({});
  });
});

// ── agent_output ───────────────────────────────────────────────────────────

describe("agent_output", () => {
  it("adds agent response to the correct round", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "proposal", agent_outputs: [], critiques: [] }],
    });
    const next = debateStreamReducer(state, { event: agentOutputEvent("Analyst") });
    expect(next.rounds[0].agent_outputs).toHaveLength(1);
    expect(next.rounds[0].agent_outputs[0].agent_name).toBe("Analyst");
  });

  it("marks agent as done in agentStatus", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "proposal", agent_outputs: [], critiques: [] }],
      agentStatus: { Analyst: "working" },
    });
    const next = debateStreamReducer(state, { event: agentOutputEvent("Analyst") });
    expect(next.agentStatus["Analyst"]).toBe("done");
  });

  it("replaces existing output for same agent (revision phase)", () => {
    const existing = { ...agentOutputEvent("Analyst"), confidence_score: 0.6 };
    const state = stateWith({
      rounds: [{
        round_number: 1,
        phase: "revision",
        agent_outputs: [{ agent_name: "Analyst", round_number: 1, position: "old", reasoning: "old", assumptions: [], confidence_score: 0.6, timestamp: "" }],
        critiques: [],
      }],
    });
    const next = debateStreamReducer(state, { event: { ...existing, confidence_score: 0.9 } });
    expect(next.rounds[0].agent_outputs).toHaveLength(1);
    expect(next.rounds[0].agent_outputs[0].confidence_score).toBe(0.9);
  });

  it("handles domain-pack agents (FinancialEthics, Security) without crashing", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "proposal", agent_outputs: [], critiques: [] }],
    });
    const next = debateStreamReducer(state, { event: agentOutputEvent("FinancialEthics") });
    expect(next.agentStatus["FinancialEthics"]).toBe("done");
  });
});

// ── critique_completed — B1 dedup ──────────────────────────────────────────

describe("critique_completed (B1 dedup)", () => {
  it("adds critique on first delivery", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "critique", agent_outputs: [], critiques: [] }],
    });
    const next = debateStreamReducer(state, { event: critiqueEvent("Risk", "Analyst") });
    expect(next.rounds[0].critiques).toHaveLength(1);
  });

  it("ignores duplicate critique (same critic+target+round)", () => {
    const existing = {
      critic_agent: "Risk", target_agent: "Analyst", round_number: 1,
      critique_points: ["Point A"], severity: "medium" as const,
      suggested_revision: null, confidence_score: 0.7,
    };
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "critique", agent_outputs: [], critiques: [existing] }],
    });
    const next = debateStreamReducer(state, { event: critiqueEvent("Risk", "Analyst") });
    expect(next.rounds[0].critiques).toHaveLength(1);
  });

  it("allows two different critiques (Risk→Analyst and Analyst→Risk)", () => {
    const state = stateWith({
      rounds: [{ round_number: 1, phase: "critique", agent_outputs: [], critiques: [] }],
    });
    const s1 = debateStreamReducer(state, { event: critiqueEvent("Risk", "Analyst") });
    const s2 = debateStreamReducer(s1, { event: critiqueEvent("Analyst", "Risk") });
    expect(s2.rounds[0].critiques).toHaveLength(2);
  });
});

// ── synthesis ─────────────────────────────────────────────────────────────

describe("synthesis", () => {
  it("stores synthesis keyed by round number", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: {
        type: "synthesis",
        round_number: 1,
        agreement_score: 0.75,
        should_continue: false,
        summary: "Good progress",
        agreement_areas: ["Timing"],
        disagreement_areas: [],
      },
    });
    expect(next.syntheses[1].agreement_score).toBe(0.75);
  });
});

// ── final_decision ─────────────────────────────────────────────────────────

describe("final_decision", () => {
  it("sets status=done and stores finalDecision", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: {
        type: "final_decision",
        thread_id: "t1",
        decision: "Proceed carefully",
        rationale_summary: "Based on analysis",
        confidence_score: 0.82,
        agreement_score: 0.78,
        risk_flags: [],
        alternatives: [],
        dissenting_opinions: [],
        debate_trace: [],
        total_rounds: 2,
        termination_reason: "consensus_reached",
        created_at: new Date().toISOString(),
      },
    });
    expect(next.status).toBe("done");
    expect(next.finalDecision?.termination_reason).toBe("consensus_reached");
    expect(next.finalDecision?.decision).toBe("Proceed carefully");
  });
});

// ── agent_timeout — B6 ────────────────────────────────────────────────────

describe("agent_timeout (B6)", () => {
  it("marks timed-out agent as done so its spinner resolves", () => {
    const state = stateWith({ agentStatus: { Analyst: "working", Risk: "working" } });
    const next = debateStreamReducer(state, {
      event: { type: "agent_timeout", round_number: 1, phase: "proposal", agent_name: "Analyst" },
    });
    expect(next.agentStatus["Analyst"]).toBe("done");
    expect(next.agentStatus["Risk"]).toBe("working");
  });
});

// ── error ─────────────────────────────────────────────────────────────────

describe("error event", () => {
  it("maps LLMResponseError to friendly message", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: { type: "error", error: "LLMResponseError: malformed output" },
    });
    expect(next.status).toBe("error");
    expect(next.error).toContain("AI model failed");
  });

  it("falls back to raw detail when error code not recognised", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: { type: "error", detail: "unknown internal error" },
    });
    expect(next.error).toBe("unknown internal error");
  });
});
