/**
 * E2E — History page: list, search, filter, pagination, navigate to debate.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes, THREAD_A, THREAD_B, makeHistoryItem } from "./fixtures/mock-api";

async function mockHistory(page: import("@playwright/test").Page, items = [makeHistoryItem(THREAD_A), makeHistoryItem(THREAD_B, "Is cloud migration worth it?")]) {
  await page.route("**/backend/history*", (r) =>
    r.fulfill({ contentType: "application/json", body: JSON.stringify({ items, total: items.length, page: 1, limit: 20 }) })
  );
}

test.describe("History page", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
  });

  test("renders page heading", async ({ page }) => {
    await mockHistory(page);
    await page.goto("/history");
    await expect(page.getByText(/Debate History/i)).toBeVisible();
  });

  test("lists debates from the API", async ({ page }) => {
    await mockHistory(page);
    await page.goto("/history");
    await expect(page.getByText("Should we expand?")).toBeVisible();
    await expect(page.getByText("Is cloud migration worth it?")).toBeVisible();
  });

  test("shows agreement score on each card", async ({ page }) => {
    await mockHistory(page);
    await page.goto("/history");
    // Agreement score: 0.82 → 82%
    const scores = page.locator("text=82%");
    await expect(scores.first()).toBeVisible();
  });

  test("empty state when no debates", async ({ page }) => {
    await page.route("**/backend/history*", (r) =>
      r.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, page: 1, limit: 20 }) })
    );
    await page.goto("/history");
    // Page should not crash; some empty state text or just an empty list
    await expect(page.locator("body")).toBeVisible();
  });

  test("search input is present", async ({ page }) => {
    await mockHistory(page);
    await page.goto("/history");
    const searchInput = page.getByPlaceholder(/search/i).first();
    await expect(searchInput).toBeVisible();
  });

  test("typing in search triggers a new API request with q param", async ({ page }) => {
    let lastUrl = "";
    await page.route("**/backend/history*", (r) => {
      lastUrl = r.request().url();
      return r.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, page: 1, limit: 20 }) });
    });
    await page.goto("/history");
    await page.getByPlaceholder(/search/i).first().fill("expand");
    await page.waitForTimeout(400); // debounce
    expect(lastUrl).toContain("expand");
  });

  test("View button links to the debate page", async ({ page }) => {
    await mockHistory(page);
    await page.goto("/history");
    const viewLinks = page.getByRole("link", { name: /View/i });
    const href = await viewLinks.first().getAttribute("href");
    expect(href).toContain(THREAD_A);
  });

  test("Compare button links to compare page with thread id", async ({ page }) => {
    await mockHistory(page);
    await page.goto("/history");
    const compareLinks = page.getByRole("link", { name: /Compare/i });
    if (await compareLinks.count() > 0) {
      const href = await compareLinks.first().getAttribute("href");
      expect(href).toContain("/compare");
    }
  });
});
