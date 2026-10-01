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
    const input = page.getByLabel("Decision query");
    await expect(input).toBeVisible();
    await input.fill("Should we expand into Asia?");
    await expect(input).toHaveValue("Should we expand into Asia?");
  });

  test("run count input accepts 2–5 runs", async ({ page }) => {
    await page.goto("/simulate");
    const runs = page.getByLabel("Runs (2–5)");
    await expect(runs).toHaveAttribute("type", "number");
    await expect(runs).toHaveAttribute("min", "2");
    await expect(runs).toHaveAttribute("max", "5");
  });

  test("submitting simulation shows stability rating", async ({ page }) => {
    await page.goto("/simulate");
    await page.getByLabel("Decision query").fill("Should we expand into Asia?");
    await page.getByRole("button", { name: /Run|Simulate/i }).first().click();
    await expect(page.getByText("High Stability")).toBeVisible({ timeout: 15_000 });
  });

  test("stable risk flags section is shown after simulation", async ({ page }) => {
    await page.goto("/simulate");
    await page.getByLabel("Decision query").fill("Should we expand into Asia?");
    await page.getByRole("button", { name: /Run|Simulate/i }).first().click();
    // Each run's own risk flags also list it; check the stable-flags section.
    const stableFlags = page.getByRole("heading", { name: /Stable Risk Flags/ }).locator("..");
    await expect(stableFlags.getByText("Currency volatility")).toBeVisible({ timeout: 15_000 });
  });

  test("consistency score is displayed", async ({ page }) => {
    await page.goto("/simulate");
    await page.getByLabel("Decision query").fill("Should we expand into Asia?");
    await page.getByRole("button", { name: /Run|Simulate/i }).first().click();
    // consistency_score = 0.81 → 81%
    await expect(page.getByText(/81%|consistency/i)).toBeVisible({ timeout: 15_000 });
  });

  test("URL-prefilled query from ?query= param is placed in input", async ({ page }) => {
    await page.goto("/simulate?query=Should+we+expand+into+Asia%3F");
    // The query is applied by an effect after the first render, so wait for it.
    await expect(page.getByLabel("Decision query")).toHaveValue(/Should we expand into Asia/);
  });
});
