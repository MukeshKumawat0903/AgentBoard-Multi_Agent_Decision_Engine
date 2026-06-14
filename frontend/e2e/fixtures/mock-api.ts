/**
 * Shared API mock helpers for Playwright E2E tests.
 *
 * All backend calls go through the Next.js /backend/* proxy.
 * page.route() intercepts those before they hit the network,
 * so no FastAPI server or GROQ_API_KEY is needed during tests.
 */

import type { Page, Route } from "@playwright/test";

// ── Canonical IDs ────────────────────────────────────────────────────────────
export const THREAD_A = "thread-e2e-aaa";
export const THREAD_B = "thread-e2e-bbb";

// ── Static response payloads ─────────────────────────────────────────────────

export const MOCK_AGENTS = [
  { name: "Analyst",  role: "Objective analyst",     icon: "📊", enabled: true,  model_provider: null, model_name: null },
  { name: "Risk",     role: "Risk assessor",          icon: "⚠️", enabled: true,  model_provider: null, model_name: null },
  { name: "Strategy", role: "Strategy proposer",      icon: "🎯", enabled: true,  model_provider: null, model_name: null },
  { name: "Ethics",   role: "Ethics evaluator",       icon: "🤝", enabled: true,  model_provider: null, model_name: null },
  { name: "Moderator",role: "Debate moderator",       icon: "🏛️", enabled: true,  model_provider: null, model_name: null },
];

export const MOCK_TEMPLATES = [
  { id: "t1", title: "Market Expansion",  category: "Business",  icon: "🌍", query: "Should we enter [market]?",  mode: "standard", tags: ["market", "expansion"] },
  { id: "t2", title: "Tech Adoption",     category: "Technology", icon: "⚙️", query: "Should we adopt [framework]?", mode: "standard", tags: ["tech", "framework"] },
  { id: "t3", title: "Risk Assessment",   category: "Strategy",   icon: "📊", query: "Evaluate the risk of [strategy]", mode: "thorough", tags: ["risk"] },
];

export const MOCK_DOMAIN_PACKS = [
  { id: "finance", name: "Finance & Investment", description: "Financial analysis pack.", icon: "💰", agents: ["Analyst","Risk","Strategy","FinancialEthics","Moderator"], paired_template_categories: ["Finance"], domain_focus: "financial risk" },
  { id: "engineering", name: "Engineering & Technology", description: "Tech decisions pack.", icon: "⚙️", agents: ["Analyst","Risk","Strategy","Security","Moderator"], paired_template_categories: ["Technology"], domain_focus: "software risk" },
];

export function makeFinalDecision(threadId: string, overrides: Record<string, unknown> = {}) {
  return {
    thread_id: threadId,
    query: "Should we expand into the Asian market in Q3?",
    decision: "Proceed with a phased expansion into South-East Asia.",
    rationale_summary: "Market analysis and risk assessment support cautious growth.",
    confidence_score: 0.85,
    agreement_score: 0.82,
    risk_flags: ["Currency volatility", "Regulatory uncertainty"],
    alternatives: ["Delay one quarter", "Partner with a local firm"],
    dissenting_opinions: [],
    minority_report: [],
    key_disagreements: [],
    agent_contribution_scores: { Analyst: 0.8, Risk: 0.75, Strategy: 0.9, Ethics: 0.7, Moderator: 0.85 },
    debate_trace: [],
    total_rounds: 2,
    termination_reason: "consensus_reached",
    created_at: "2026-06-04T10:00:00Z",
    ...overrides,
  };
}

export function makeHistoryItem(threadId: string, query = "Should we expand?") {
  return {
    thread_id: threadId,
    user_query: query,
    created_at: "2026-06-04T10:00:00Z",
    status: "converged",
    total_rounds: 2,
    agreement_score: 0.82,
    termination_reason: "consensus_reached",
  };
}

// ── SSE stream body builder ───────────────────────────────────────────────────

type SSEEvent = { type: string; data: Record<string, unknown> };

export function buildSSEBody(events: SSEEvent[]): string {
  return events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e.data)}\n`).join("\n") + "\n";
}

export function makeDebateSSEEvents(threadId: string): SSEEvent[] {
  const decision = makeFinalDecision(threadId);
  return [
    { type: "debate_started",   data: { type: "debate_started",   thread_id: threadId, user_query: decision.query, max_rounds: 2 } },
    { type: "round_started",    data: { type: "round_started",    round_number: 1, max_rounds: 2 } },
    { type: "phase_started",    data: { type: "phase_started",    round_number: 1, phase: "proposal" } },
    { type: "agent_output",     data: { type: "agent_output",     round_number: 1, phase: "proposal", agent_name: "Analyst", position: "Proceed with phased rollout.", reasoning: "Market data is positive.", confidence_score: 0.85, assumptions: ["Stable macroeconomics"] } },
    { type: "agent_output",     data: { type: "agent_output",     round_number: 1, phase: "proposal", agent_name: "Risk",    position: "Proceed with caution.",      reasoning: "Currency risk is material.",  confidence_score: 0.75, assumptions: ["Hedging in place"] } },
    { type: "phase_started",    data: { type: "phase_started",    round_number: 1, phase: "critique" } },
    { type: "critique_completed",data: { type: "critique_completed", round_number: 1, critic_agent: "Risk", target_agent: "Analyst", severity: "medium", critique_points: ["Currency risk not addressed."], confidence_score: 0.7 } },
    { type: "synthesis",        data: { type: "synthesis",        round_number: 1, agreement_score: 0.82, should_continue: false, summary: "Broad consensus on phased approach.", agreement_areas: ["Timing", "Phase structure"], disagreement_areas: ["Currency hedging"] } },
    { type: "debate_completed", data: { type: "debate_completed", thread_id: threadId, termination_reason: "consensus_reached", total_rounds: 1, agreement_score: 0.82 } },
    { type: "final_decision",   data: { type: "final_decision",   ...decision } },
  ];
}

// ── Route setup helpers ───────────────────────────────────────────────────────

export async function mockStaticRoutes(page: Page) {
  await page.route("**/backend/agents",        (r) => json(r, MOCK_AGENTS));
  await page.route("**/backend/templates",     (r) => json(r, MOCK_TEMPLATES));
  await page.route("**/backend/domain-packs",  (r) => json(r, MOCK_DOMAIN_PACKS));
  await page.route("**/backend/health",        (r) => json(r, { status: "ok", version: "2.0.0", groq_configured: true }));
  await page.route("**/backend/llm-settings",  (r) => json(r, { provider: "groq", model: "llama-3.3-70b-versatile", available_models: { groq: [], openai: [], anthropic: [] }, using_custom_key: false }));
  await page.route("**/backend/history*",      (r) => json(r, { items: [makeHistoryItem(THREAD_A), makeHistoryItem(THREAD_B, "Is cloud migration worth it?")], total: 2, page: 1, limit: 20 }));
}

export async function mockDebateStartAsync(page: Page, threadId = THREAD_A) {
  await page.route("**/backend/debate/start-async", (r) =>
    json(r, { thread_id: threadId, status: "initialized", stream_url: `/debate/${threadId}/stream` })
  );
}

export async function mockDebateStream(page: Page, threadId = THREAD_A) {
  await page.route(`**/backend/debate/${threadId}/stream`, (route) =>
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
      body: buildSSEBody(makeDebateSSEEvents(threadId)),
    })
  );
}

export async function mockHistoryItem(page: Page, threadId: string) {
  await page.route(`**/backend/history/${threadId}`, (r) =>
    json(r, makeFinalDecision(threadId))
  );
}

export async function mockSimulation(page: Page) {
  const decisions = [
    makeFinalDecision("sim-run-1"),
    makeFinalDecision("sim-run-2", { termination_reason: "max_rounds_reached" }),
    makeFinalDecision("sim-run-3"),
  ];
  await page.route("**/backend/debate/simulate*", (r) =>
    json(r, {
      query: "Should we expand?",
      runs: 3,
      decisions,
      consistency_score: 0.81,
      confidence_variance: 0.03,
      avg_agreement_score: 0.81,
      stable_risk_flags: ["Currency volatility"],
      stability_rating: "High",
    })
  );
}

export async function mockExport(page: Page, threadId: string) {
  await page.route(`**/backend/decision/${threadId}/export*`, (route) => {
    const url = route.request().url();
    if (url.includes("format=pdf")) {
      route.fulfill({ status: 200, headers: { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename="decision-${threadId}.pdf"` }, body: "%PDF-1.4 fake pdf" });
    } else {
      route.fulfill({ status: 200, headers: { "Content-Type": "text/markdown", "Content-Disposition": `attachment; filename="decision-${threadId}.md"` }, body: `# Decision\n\nProceed with phased expansion.` });
    }
  });
}

// ── Tiny helpers ─────────────────────────────────────────────────────────────

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}
