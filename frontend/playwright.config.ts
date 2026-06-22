import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = 3173;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["html", { outputFolder: "playwright-report" }],
    ["list"],
  ],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: process.env.CI ? "retain-on-failure" : "off",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          // CI-friendly flags
          args: ["--no-sandbox", "--disable-setuid-sandbox"],
        },
      },
    },
    {
      name: "msedge",
      use: {
        ...devices["Desktop Edge"],
        channel: "msedge",
      },
    },
  ],

  webServer: {
    command: "npx vite --port 3173 --strictPort",
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    cwd: __dirname,
  },

  outputDir: "test-results",
});
