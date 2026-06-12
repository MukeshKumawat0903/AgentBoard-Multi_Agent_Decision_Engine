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

  test("shows the page title", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Multi-Agent Decision Engine" })).toBeVisible();
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
    const financePack = page.getByRole("button", { name: /Finance & Investment/ });
    await expect(financePack).toBeVisible();
    await financePack.click();
    // Clicking shows the domain pack description
    await expect(page.getByText(/Financial analysis pack/i)).toBeVisible();
  });

  test("domain pack can be deselected by clicking again", async ({ page }) => {
    await page.goto("/");
    const financePack = page.getByRole("button", { name: /Finance & Investment/ });
    await financePack.click();
    await expect(page.getByText(/Financial analysis pack/i)).toBeVisible();
    await financePack.click();
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
    await expect(page.getByText("Recent debates")).toBeVisible();
    await expect(page.getByText("Should we expand?")).toBeVisible();
  });

  test("agent roster lists the participating agents", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("5 core agents")).toBeVisible();
    await expect(page.getByRole("button", { name: /Analyst/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moderator/ })).toBeVisible();
  });

  test("selecting a domain pack switches the roster to the pack's agents", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Finance & Investment/ }).click();
    await expect(page.getByText(/domain expert/i)).toBeVisible();
    await expect(page.getByText("FinancialEthics")).toBeVisible();
  });
});
