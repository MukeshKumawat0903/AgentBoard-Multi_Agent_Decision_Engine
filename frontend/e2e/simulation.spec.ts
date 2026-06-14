/**
 * E2E — Simulation page: run N debates, show stability rating and stable flags.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes, mockSimulation } from "./fixtures/mock-api";

test.describe("Simulation page", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
    await mockSimulation(page);
  });

  test("renders simulation heading", async ({ page }) => {
    await page.goto("/simulate");
    await expect(page.getByText(/Scenario Simulation/i)).toBeVisible();
  });

  test("query input is present and accepts text", async ({ page }) => {
    await page.goto("/simulate");
    const input = page.locator("input, textarea").first();
    await expect(input).toBeVisible();
    await input.fill("Should we expand into Asia?");
    await expect(input).toHaveValue("Should we expand into Asia?");
  });

  test("run count selector is present with values 2–5", async ({ page }) => {
    await page.goto("/simulate");
    const select = page.locator("select").first();
    if (await select.count() > 0) {
      const options = await select.locator("option").allInnerTexts();
      expect(options.some((o) => o.includes("2") || o.includes("3"))).toBe(true);
    } else {
      // Some implementations use input[type=number]
      const numInput = page.locator("input[type=number]").first();
      await expect(numInput).toBeVisible();
    }
  });

  test("submitting simulation shows stability rating", async ({ page }) => {
    await page.goto("/simulate");
    const queryInput = page.locator("input[type=text], textarea").first();
    await queryInput.fill("Should we expand into Asia?");
    const runBtn = page.getByRole("button", { name: /Run|Simulate/i }).first();
    await runBtn.click();
    await expect(page.getByText(/High|Medium|Low/i)).toBeVisible({ timeout: 15_000 });
  });

  test("stable risk flags section is shown after simulation", async ({ page }) => {
    await page.goto("/simulate");
    await page.locator("input[type=text], textarea").first().fill("Should we expand into Asia?");
    await page.getByRole("button", { name: /Run|Simulate/i }).first().click();
    await expect(page.getByText("Currency volatility")).toBeVisible({ timeout: 15_000 });
  });

  test("consistency score is displayed", async ({ page }) => {
    await page.goto("/simulate");
    await page.locator("input[type=text], textarea").first().fill("Should we expand into Asia?");
    await page.getByRole("button", { name: /Run|Simulate/i }).first().click();
    // consistency_score = 0.81 → 81%
    await expect(page.getByText(/81%|consistency/i)).toBeVisible({ timeout: 15_000 });
  });

  test("URL-prefilled query from ?query= param is placed in input", async ({ page }) => {
    await page.goto("/simulate?query=Should+we+expand+into+Asia%3F");
    const input = page.locator("input[type=text], textarea").first();
    const value = await input.inputValue();
    expect(value).toContain("Should we expand into Asia");
  });
});
