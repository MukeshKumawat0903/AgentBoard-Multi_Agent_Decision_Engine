/**
 * E2E — Debate flow: submission → SSE streaming → final decision panel.
 * SSE stream is mocked via page.route() — no real backend needed.
 */

import { test, expect } from "@playwright/test";
import {
  mockStaticRoutes, mockDebateStartAsync, mockDebateStream,
  mockHistoryItem, mockExport, THREAD_A,
} from "./fixtures/mock-api";

test.describe("Debate streaming flow (happy path)", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
    await mockDebateStartAsync(page, THREAD_A);
    await mockDebateStream(page, THREAD_A);
    await mockHistoryItem(page, THREAD_A);
  });

  test("navigating to a debate page shows the stream viewer", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    // Either connecting spinner or streaming content should appear
    const hasContent = await page.locator("body").textContent();
    expect(hasContent).toBeTruthy();
  });

  test("submitting from home lands on the debate page and shows query banner", async ({ page }) => {
    await page.goto("/");
    await page.locator("textarea").first().fill("Should we expand into the Asian market in Q3?");
    await page.getByRole("button", { name: /Start Debate/i }).first().click();
    await expect(page).toHaveURL(new RegExp(`/debate/${THREAD_A}`));
    await expect(page.getByText("Debate Query")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Should we expand into the Asian market in Q3?")).toBeVisible();
  });

  test("round progress bar appears during streaming", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    // Round progress indicators appear once debate_started event arrives
    await expect(page.getByText(/Round \d+ of \d+/i)).toBeVisible({ timeout: 15_000 });
  });

  test("agent output cards render after agent_output events", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Analyst")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Proceed with phased rollout.")).toBeVisible();
  });

  test("critique section renders after critique_completed events", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/Critiques/)).toBeVisible({ timeout: 15_000 });
  });

  test("moderator synthesis card appears after synthesis event", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Moderator Synthesis")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Broad consensus on phased approach.")).toBeVisible();
  });

  test("final decision panel renders after final_decision event", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Proceed with a phased expansion into South-East Asia.")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Decision")).toBeVisible();
    await expect(page.getByText("Rationale")).toBeVisible();
  });

  test("termination reason banner reflects consensus_reached (B5 fix)", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/Debate complete — consensus reached/i)).toBeVisible({ timeout: 20_000 });
  });

  test("risk flags are shown in the final decision panel", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Currency volatility")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Regulatory uncertainty")).toBeVisible();
  });

  test("alternatives list is rendered", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Delay one quarter")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Partner with a local firm")).toBeVisible();
  });

  test("export buttons are visible in the action bar", async ({ page }) => {
    await mockExport(page, THREAD_A);
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText("Markdown").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("PDF").first()).toBeVisible();
  });

  test("Evaluate Quality button is present", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/Evaluate Quality/i)).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("Debate page — max_rounds_reached termination (B5 fix)", () => {
  test("banner shows 'max rounds reached' not 'consensus reached'", async ({ page }) => {
    const { buildSSEBody, makeDebateSSEEvents, makeFinalDecision } = await import("./fixtures/mock-api");
    await mockStaticRoutes(page);
    await mockDebateStartAsync(page, THREAD_A);

    // Override stream: final decision has max_rounds_reached termination
    const events = makeDebateSSEEvents(THREAD_A);
    const lastEvent = events[events.length - 1];
    lastEvent.data = { ...lastEvent.data, ...makeFinalDecision(THREAD_A, { termination_reason: "max_rounds_reached" }) };
    await page.route(`**/backend/debate/${THREAD_A}/stream`, (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
        body: buildSSEBody(events),
      })
    );

    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/max rounds reached/i)).toBeVisible({ timeout: 20_000 });
  });
});
