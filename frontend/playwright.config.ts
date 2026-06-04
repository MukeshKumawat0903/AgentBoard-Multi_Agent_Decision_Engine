import { defineConfig, devices } from "@playwright/test";

/**
 * AgentBoard E2E test configuration.
 *
 * Tests mock all backend API calls via page.route() so no FastAPI server
 * or API key is needed.  The Next.js dev server is started automatically.
 *
 * Run:  npm run e2e
 * UI:   npm run e2e:ui
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,     // SSE mocks are stateful; keep serial
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],

  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    // All tests intercept /backend/* via page.route() — no real backend needed.
    extraHTTPHeaders: { "Accept": "application/json" },
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Start the Next.js dev server automatically before running tests.
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
