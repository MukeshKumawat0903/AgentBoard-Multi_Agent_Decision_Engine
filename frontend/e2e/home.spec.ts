/**
 * E2E — Home page: form, templates, domain packs, validation, recent debates.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes, mockDebateStartAsync, THREAD_A, MOCK_TEMPLATES } from "./fixtures/mock-api";

test.describe("Home page", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
    await mockDebateStartAsync(page, THREAD_A);
  });

  test("shows hero title and description", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Multi-Agent Decision Engine")).toBeVisible();
    await expect(page.getByText(/specialised AI agents/i)).toBeVisible();
  });

  test("debate input textarea is present and accepts text", async ({ page }) => {
    await page.goto("/");
    const textarea = page.locator("textarea").first();
    await expect(textarea).toBeVisible();
    await textarea.fill("Should we expand into the Asian market in Q3?");
    await expect(textarea).toHaveValue("Should we expand into the Asian market in Q3?");
  });

  test("short query is blocked — Start Debate button disabled below 10 chars", async ({ page }) => {
    await page.goto("/");
    const textarea = page.locator("textarea").first();
    await textarea.fill("Too short");
    const submitBtn = page.getByRole("button", { name: /Start Debate|Debate/i }).first();
    // Button should be disabled or form invalid for short queries
    const isDisabled = await submitBtn.isDisabled();
    if (!isDisabled) {
      // Some implementations show inline error rather than disabling the button
      await submitBtn.click();
      await expect(page.getByText(/at least 10 characters|too short/i)).toBeVisible();
    }
  });

  test("Browse templates button expands the template grid", async ({ page }) => {
    await page.goto("/");
    await page.getByText(/Browse templates/i).click();
    await expect(page.getByText(MOCK_TEMPLATES[0].title)).toBeVisible();
    await expect(page.getByText(MOCK_TEMPLATES[1].title)).toBeVisible();
  });

  test("template search filters by text", async ({ page }) => {
    await page.goto("/");
    await page.getByText(/Browse templates/i).click();
    const search = page.getByPlaceholder(/Search templates/i);
    await search.fill("Market");
    await expect(page.getByText("Market Expansion")).toBeVisible();
    await expect(page.getByText("Tech Adoption")).not.toBeVisible();
  });

  test("selecting a template pre-fills the query textarea", async ({ page }) => {
    await page.goto("/");
    await page.getByText(/Browse templates/i).click();
    await page.getByText(MOCK_TEMPLATES[0].title).click();
    const textarea = page.locator("textarea").first();
    await expect(textarea).toHaveValue(/Should we enter/);
  });

  test("domain pack selector appears and responds to clicks", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Finance & Investment")).toBeVisible();
    await page.getByText("Finance & Investment").click();
    // Clicking shows the domain pack description
    await expect(page.getByText(/Financial analysis pack/i)).toBeVisible();
  });

  test("domain pack can be deselected by clicking again", async ({ page }) => {
    await page.goto("/");
    await page.getByText("Finance & Investment").click();
    await expect(page.getByText(/Financial analysis pack/i)).toBeVisible();
    await page.getByText("Finance & Investment").click();
    await expect(page.getByText(/Financial analysis pack/i)).not.toBeVisible();
  });

  test("submitting a valid query navigates to the debate page", async ({ page }) => {
    await page.goto("/");
    await page.locator("textarea").first().fill("Should we expand into the Asian market in Q3?");
    await page.getByRole("button", { name: /Start Debate/i }).first().click();
    await expect(page).toHaveURL(new RegExp(`/debate/${THREAD_A}`));
  });

  test("recent debates section shows when history is available", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Recent Debates")).toBeVisible();
    await expect(page.getByText("Should we expand?")).toBeVisible();
  });

  test("feature cards are visible at the bottom", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("5 Expert Agents")).toBeVisible();
    await expect(page.getByText("Structured Debate")).toBeVisible();
    await expect(page.getByText("Converged Decisions")).toBeVisible();
  });
});
