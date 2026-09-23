import { defineConfig, devices } from "@playwright/test";

const PORT = process.env.E2E_PORT || "3000";
const BASE = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  use: {
    baseURL: BASE,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev -- -p ${PORT}`,
    env: {
      NEXT_PUBLIC_API_URL: BASE,
    },
    cwd: __dirname,
    url: BASE,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
