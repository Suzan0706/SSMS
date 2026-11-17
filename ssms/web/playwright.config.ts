import { defineConfig } from "@playwright/test";

// E2E needs the API running on a seeded database (see ssms/README.md "End-to-end tests").
// The web app is served by `vite preview`, which proxies /api to SSMS_API_URL.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173",
    channel: process.env.E2E_BROWSER_CHANNEL ?? "chrome",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
