// Vitest runs the web UI's unit and component tests: `npm test`.
// The tests run in Node.js, in jsdom, a browser imitation, so they need no
// real browser. The end-to-end tests in e2e/ use a real one (Playwright).
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    // Undo every mock and stubbed global after each test, so tests can't affect each other.
    restoreMocks: true,
    unstubGlobals: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/types/**"],
      reporter: ["text", "html"],
      // The same bar as the Python code: CI fails below these numbers.
      thresholds: { lines: 95, statements: 95, functions: 95, branches: 95 },
    },
  },
});
