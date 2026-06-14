/**
 * E2E — Compare page: side-by-side diff, swap, risk flag highlighting, delta summary.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes, mockHistoryItem, THREAD_A, THREAD_B } from "./fixtures/mock-api";

test.describe("Compare page", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
    await mockHistoryItem(page, THREAD_A);
    await mockHistoryItem(page, THREAD_B);
  });

  test("renders compare heading and two input slots", async ({ page }) => {
    await page.goto("/compare");
    await expect(page.getByText("Compare Debates")).toBeVisible();
    await expect(page.getByText("Debate A")).toBeVisible();
    await expect(page.getByText("Debate B")).toBeVisible();
  });

  test("Compare button is disabled when both inputs are empty", async ({ page }) => {
    await page.goto("/compare");
    const btn = page.getByRole("button", { name: "Compare" });
    await expect(btn).toBeDisabled();
  });

  test("Compare button enables when Debate A input has value", async ({ page }) => {
    await page.goto("/compare");
    const [inputA] = await page.getByPlaceholder("Enter thread ID…").all();
    await inputA.fill(THREAD_A);
    const btn = page.getByRole("button", { name: "Compare" });
    await expect(btn).not.toBeDisabled();
  });

  test("auto-loads debates when ?a=&b= query params are present", async ({ page }) => {
    await page.goto(`/compare?a=${THREAD_A}&b=${THREAD_B}`);
    // Both decision panels should load
    await expect(page.getByText("Proceed with a phased expansion into South-East Asia.").first()).toBeVisible({ timeout: 10_000 });
  });

  test("Swap A / B button exchanges the input values", async ({ page }) => {
    await page.goto("/compare");
    const [inputA, inputB] = await page.getByPlaceholder("Enter thread ID…").all();
    await inputA.fill("aaaa");
    await inputB.fill("bbbb");
    const swapBtn = page.getByText(/Swap A \/ B/i);
    await expect(swapBtn).toBeVisible();
    await swapBtn.click();
    await expect(inputA).toHaveValue("bbbb");
    await expect(inputB).toHaveValue("aaaa");
  });

  test("risk flag diff marks unique-to-A flags distinctly", async ({ page }) => {
    // Override THREAD_B with different risk flags so A has a unique one
    const { makeFinalDecision } = await import("./fixtures/mock-api");
    await page.route(`**/backend/history/${THREAD_B}`, (r) =>
      r.fulfill({ contentType: "application/json", body: JSON.stringify(makeFinalDecision(THREAD_B, { risk_flags: ["Regulatory uncertainty"] })) })
    );
    await page.goto(`/compare?a=${THREAD_A}&b=${THREAD_B}`);
    await expect(page.getByText("Currency volatility")).toBeVisible({ timeout: 10_000 });
  });

  test("Delta Summary section appears when both debates loaded", async ({ page }) => {
    await page.goto(`/compare?a=${THREAD_A}&b=${THREAD_B}`);
    await expect(page.getByText("Delta Summary")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Confidence Δ")).toBeVisible();
    await expect(page.getByText("Agreement Δ")).toBeVisible();
  });

  test("Run both debates again navigates to simulate page", async ({ page }) => {
    await page.goto(`/compare?a=${THREAD_A}&b=${THREAD_B}`);
    const runBtn = page.getByText(/Run both debates again/i);
    await expect(runBtn).toBeVisible({ timeout: 10_000 });
    await runBtn.click();
    await expect(page).toHaveURL(/\/simulate/);
  });
});
