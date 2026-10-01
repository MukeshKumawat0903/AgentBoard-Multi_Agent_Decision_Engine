/**
 * E2E — Human-in-the-loop review.
 *
 * "Add round" race: the next round can finish and pause for review again
 * before the approve request's own response comes back. That newer approval
 * request must stay on screen instead of being cleared by the older response.
 */

import { test, expect, type Route } from "@playwright/test";
import { mockStaticRoutes, THREAD_A } from "./fixtures/mock-api";

type SSEEvent = { type: string; data: Record<string, unknown> };

/** SSE body with ids, like the real backend, so reconnects resume instead of replaying. */
function sseWithIds(events: SSEEvent[], firstId: number): string {
  return events
    .map((e, i) => `id: ${firstId + i}\nevent: ${e.type}\ndata: ${JSON.stringify(e.data)}\n`)
    .join("\n") + "\n";
}

const QUERY = "Which vendor should we pick for the rollout?";

function approvalEvent(round: number) {
  return {
    type: "approval_required",
    data: {
      type: "approval_required",
      round_number: round,
      agreement_score: 0.7 + round / 100,
      termination_reason: round === 1 ? "consensus_reached" : "max_rounds_reached",
      synthesis_summary: `Summary after round ${round}.`,
      options: ["approve", "override", "add_round"],
    },
  };
}

function roundEvents(round: number, maxRounds: number) {
  return [
    { type: "round_started", data: { type: "round_started", round_number: round, max_rounds: maxRounds } },
    {
      type: "agent_output",
      data: {
        type: "agent_output", round_number: round, phase: "proposal", agent_name: "Analyst",
        position: `Analyst view, round ${round}.`, reasoning: "r", confidence_score: 0.8, assumptions: [],
      },
    },
  ];
}

test.describe("HITL approval", () => {
  test("a second approval request that arrives before the add-round response stays visible", async ({ page }) => {
    await mockStaticRoutes(page);
    await page.route(`**/backend/history/${THREAD_A}`, (r) =>
      r.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not found" }) }),
    );

    let addRoundClicked = false;
    let round2Served = false;

    await page.route(`**/backend/debate/${THREAD_A}/stream*`, (route: Route) => {
      const events: SSEEvent[] = [
        { type: "debate_started", data: { type: "debate_started", thread_id: THREAD_A, user_query: QUERY, max_rounds: 2, agents: ["Analyst"] } },
        ...roundEvents(1, 2),
        approvalEvent(1),
      ];
      if (addRoundClicked) {
        // The extra round has run and paused for review again.
        events.push(...roundEvents(2, 3), approvalEvent(2));
      }
      // Resume after the last event the client saw, as the backend does.
      const lastSeen = Number(new URL(route.request().url()).searchParams.get("last_event_id") ?? 0);
      const pending = events.slice(lastSeen);
      if (addRoundClicked && pending.some((e) => e.data.round_number === 2 && e.type === "approval_required")) {
        round2Served = true;
      }
      return route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
        body: sseWithIds(pending, lastSeen + 1),
      });
    });

    await page.route(`**/backend/debate/${THREAD_A}/approve`, async (route: Route) => {
      addRoundClicked = true;
      // Hold the 202 until the stream has delivered the round-2 approval request.
      const deadline = Date.now() + 15_000;
      while (!round2Served && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      await new Promise((resolve) => setTimeout(resolve, 1_000));
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ thread_id: THREAD_A, status: "resuming", action: "add_round" }),
      });
    });

    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Human Review Required")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Round 1 — Agreement/)).toBeVisible();

    const approveResponse = page.waitForResponse(`**/backend/debate/${THREAD_A}/approve`);
    await page.getByRole("button", { name: "+ Add Round" }).click();
    await approveResponse;

    // The answered round-1 request is gone; the newer round-2 request remains.
    await expect(page.getByText(/Round 2 — Agreement/)).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(1_000);
    await expect(page.getByText("Human Review Required")).toBeVisible();
    await expect(page.getByText(/Round 2 — Agreement/)).toBeVisible();
  });
});
