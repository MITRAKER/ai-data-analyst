import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests: `npm run build`, then `npm run test:e2e`.
 *
 * Playwright starts two servers: the built web UI (e2e/web-server.mts), and
 * e2e/fake-api.mts in place of the Python API. Then it uses the app in
 * Chromium, as a person would, on a desktop screen and on a phone screen.
 */
const WEB_PORT = "3100";
const API_PORT = "8100";

// To use a Chromium that is already installed, instead of the one that
// `npx playwright install chromium` downloads, set PLAYWRIGHT_CHROMIUM to its path.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: process.env.CI !== undefined,
  reporter: process.env.CI === undefined ? "list" : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "off",
    screenshot: "only-on-failure",
    launchOptions: executablePath === undefined ? {} : { executablePath },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: `node e2e/fake-api.mts ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/health`,
    },
    {
      command: "node e2e/web-server.mts",
      url: `http://127.0.0.1:${WEB_PORT}/api/health`,
      env: { PORT: WEB_PORT, HOSTNAME: "127.0.0.1", BACKEND_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
