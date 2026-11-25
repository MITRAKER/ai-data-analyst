// Runs before every test file.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Start each test without the host names that your own shell may allow, so
// that the tests of the host check work the same on every computer.
beforeEach(() => {
  vi.stubEnv("ALLOWED_HOSTS", "");
});

// Remove what each test rendered, so the next test starts with an empty page.
afterEach(() => {
  cleanup();
});
