/**
 * E2E — Dark mode: toggle button switches theme, preference persists on reload.
 */

import { test, expect } from "@playwright/test";
import { mockStaticRoutes } from "./fixtures/mock-api";

test.describe("Dark mode", () => {
  test.beforeEach(async ({ page }) => {
    await mockStaticRoutes(page);
  });

  test("theme toggle button is present in the nav bar", async ({ page }) => {
    await page.goto("/");
    const toggleBtn = page.getByRole("button", { name: /toggle dark mode/i });
    await expect(toggleBtn).toBeVisible();
  });

  test("clicking toggle adds 'dark' class to <html>", async ({ page }) => {
    await page.goto("/");
    const html = page.locator("html");
    const initialDark = await html.evaluate((el) => el.classList.contains("dark"));

    await page.getByRole("button", { name: /toggle dark mode/i }).click();
    const afterToggle = await html.evaluate((el) => el.classList.contains("dark"));
    expect(afterToggle).toBe(!initialDark);
  });

  test("clicking toggle twice returns to original theme", async ({ page }) => {
    await page.goto("/");
    const html = page.locator("html");
    const initial = await html.evaluate((el) => el.classList.contains("dark"));

    const btn = page.getByRole("button", { name: /toggle dark mode/i });
    await btn.click();
    await btn.click();

    const final = await html.evaluate((el) => el.classList.contains("dark"));
    expect(final).toBe(initial);
  });

  test("dark preference is saved to localStorage", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /toggle dark mode/i }).click();
    const theme = await page.evaluate(() => localStorage.getItem("theme"));
    expect(["dark", "light"]).toContain(theme);
  });

  test("dark mode persists after page reload", async ({ page }) => {
    await page.goto("/");
    const html = page.locator("html");

    // Force dark mode on
    await page.evaluate(() => {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    });

    await page.reload();

    // The inline script in layout.tsx should restore dark from localStorage
    const isDark = await html.evaluate((el) => el.classList.contains("dark"));
    expect(isDark).toBe(true);
  });

  test("nav links and content are readable in dark mode", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      document.documentElement.classList.add("dark");
    });
    // Basic sanity: key nav elements still visible
    await expect(page.getByText("AgentBoard")).toBeVisible();
  });

  test("dark mode on history page", async ({ page }) => {
    await page.goto("/history");
    await page.getByRole("button", { name: /toggle dark mode/i }).click();
    const isDark = await page.locator("html").evaluate((el) => el.classList.contains("dark"));
    expect(isDark).toBe(true);
  });
});
