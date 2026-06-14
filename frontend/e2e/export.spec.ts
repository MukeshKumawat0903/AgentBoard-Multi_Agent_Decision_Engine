/**
 * E2E — Export flow: Markdown and PDF download from the final decision panel.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes, mockDebateStartAsync, mockDebateStream, mockHistoryItem, mockExport, THREAD_A } from "./fixtures/mock-api";

test.describe("Export flow", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
    await mockDebateStartAsync(page, THREAD_A);
    await mockDebateStream(page, THREAD_A);
    await mockHistoryItem(page, THREAD_A);
    await mockExport(page, THREAD_A);
  });

  test("Markdown export triggers a file download", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    // Wait for debate to complete and action bar to appear
    await expect(page.getByText(/Markdown/i).first()).toBeVisible({ timeout: 20_000 });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByText(/Markdown/i).first().click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/\.md$/);
  });

  test("PDF export triggers a file download", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/PDF/i).first()).toBeVisible({ timeout: 20_000 });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByText(/PDF/i).first().click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  });

  test("JSON download button works", async ({ page }) => {
    await page.goto(`/debate/${THREAD_A}`);
    await expect(page.getByText(/JSON/i).first()).toBeVisible({ timeout: 20_000 });

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      // JSON button triggers a blob URL download — no network request mocked
      page.getByText(/JSON/i).first().click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/\.json$/);
  });
});
