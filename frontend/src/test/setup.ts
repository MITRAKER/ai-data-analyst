// Runs before every test file.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Start each test as if ALLOWED_HOSTS were not set (as with `npm run dev`,
// `npm start` and the browser tests), whatever your own shell sets, so that
// the tests of the host check work the same on every computer.
beforeEach(() => {
  vi.stubEnv("ALLOWED_HOSTS", undefined);
});

// Remove what each test rendered, so the next test starts with an empty page.
afterEach(() => {
  cleanup();
});
