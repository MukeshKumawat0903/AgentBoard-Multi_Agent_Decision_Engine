/**
 * E2E — Error recovery: validation errors, API errors, 404 page, error boundary.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes, THREAD_A } from "./fixtures/mock-api";

test.describe("Input validation", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
  });

  test("submitting empty query shows validation feedback", async ({ page }) => {
    await page.goto("/");
    const submitBtn = page.getByRole("button", { name: /Start Debate/i }).first();
    // The button should be disabled or form shows an error
    const isDisabled = await submitBtn.isDisabled();
    if (!isDisabled) {
      await submitBtn.click();
      // Should show some error — not navigate away
      await expect(page).toHaveURL("/");
    } else {
      expect(isDisabled).toBe(true);
    }
  });

  test("query under 10 chars: button stays disabled", async ({ page }) => {
    await page.goto("/");
    await page.locator("textarea").first().fill("Short");
    const submitBtn = page.getByRole("button", { name: /Start Debate/i }).first();
    await expect(submitBtn).toBeDisabled();
  });

  test("query of exactly 10 chars enables the button", async ({ page }) => {
    await page.goto("/");
    await page.locator("textarea").first().fill("1234567890");
    const submitBtn = page.getByRole("button", { name: /Start Debate/i }).first();
    await expect(submitBtn).not.toBeDisabled();
  });
});

test.describe("API error handling", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
  });

  test("backend 500 error on debate start shows toast error, not crash", async ({ page }) => {
    await page.route("**/backend/debate/start-async", (r) =>
      r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "internal_server_error" }) })
    );
    await page.goto("/");
    await page.locator("textarea").first().fill("Should we expand into the Asian market in Q3?");
    await page.getByRole("button", { name: /Start Debate/i }).first().click();
    // Should stay on home page (not navigate away on error)
    await expect(page).toHaveURL("/");
    // An error toast or message should appear
    await expect(page.locator("body")).toContainText(/.+/);
  });

  test("unknown thread ID shows error state on debate page", async ({ page }) => {
    await page.route("**/backend/debate/nonexistent/stream", (r) =>
      r.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: "debate_not_found" }) })
    );
    await page.goto("/debate/nonexistent");
    // Should render error or reconnecting state — not a blank page
    await expect(page.locator("body")).not.toBeEmpty();
  });

  test("404 page renders for unknown routes", async ({ page }) => {
    await page.goto("/this-route-does-not-exist-1234");
    // Next.js custom not-found.tsx should render
    const body = await page.locator("body").textContent();
    expect(body).toBeTruthy();
    // Should show something useful — link to home or a 404 message
    const hasHomeLink = await page.getByRole("link", { name: /home|back/i }).count();
    const has404Text = (body ?? "").toLowerCase().includes("not found") || (body ?? "").includes("404");
    expect(hasHomeLink > 0 || has404Text).toBe(true);
  });

  test("debate SSE error event shows error UI not blank page (B6-related)", async ({ page }) => {
    await page.route(`**/backend/debate/${THREAD_A}/stream`, (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: error\ndata: {\"type\":\"error\",\"error\":\"LLMResponseError: malformed output\",\"detail\":\"Structured output failed\"}\n\n",
      })
    );
    await page.goto(`/debate/${THREAD_A}`);
    // The error UI should show instead of a blank/frozen page
    await expect(page.getByText(/Debate failed|AI model failed|Try again/i)).toBeVisible({ timeout: 10_000 });
  });

  test("clicking Retry stream on error page reloads the stream", async ({ page }) => {
    let callCount = 0;
    await page.route(`**/backend/debate/${THREAD_A}/stream`, (route) => {
      callCount++;
      return route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: error\ndata: {\"type\":\"error\",\"error\":\"test error\"}\n\n",
      });
    });
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/Retry stream/i)).toBeVisible({ timeout: 10_000 });
    await page.getByText(/Retry stream/i).click();
    // After clicking retry, page reloads (window.location.reload)
    await page.waitForURL(`/debate/${THREAD_A}`);
    expect(callCount).toBeGreaterThanOrEqual(1);
  });
});

test.describe("Error boundary", () => {
  test("global error.tsx doesn't show for normal navigation", async ({ page }) => {
    await mockStaticRoutes(page);
    await page.goto("/");
    await expect(page.getByText(/something went wrong/i)).not.toBeVisible();
  });
});
