import { expect, expectAccessible, openApp, SUGGESTION, test } from "./fixtures";

test("sends security headers, with a new nonce for every page", async ({ page }) => {
  const first = await page.goto("/");
  const headers = first?.headers() ?? {};
  const policy = headers["content-security-policy"] ?? "";
  expect(policy).toContain("default-src 'self'");
  expect(policy).toContain("frame-ancestors 'none'");
  expect(policy).toMatch(/script-src 'self' 'nonce-[\w+/=]+' 'strict-dynamic'/);
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("no-referrer");
  expect(headers["x-powered-by"]).toBeUndefined();

  const second = await page.reload();
  expect(second?.headers()["content-security-policy"]).not.toBe(policy);
});

test("has no accessibility problems, in light or dark mode", async ({ page }) => {
  await openApp(page);
  await expectAccessible(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

test("explains why the agent can't answer yet", async ({ page }) => {
  // Only this test: the API says that it has no Claude API key.
  await page.route("**/api/agent/status", (route) =>
    route.fulfill({ json: { ready: false, detail: "ANTHROPIC_API_KEY is not set." } }),
  );
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("ANTHROPIC_API_KEY is not set.");
  await expect(page.getByRole("button", { name: "sales", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: SUGGESTION })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
  await expectAccessible(page);
});

test("shows a dataset's columns and first rows", async ({ page }) => {
  await openApp(page);
  await page.getByRole("button", { name: "sales", exact: true }).click();
  const details = page.getByRole("region", { name: "Details of sales" });
  await expect(details).toContainText("2,000 rows, 3 columns");
  await expect(details.getByText("TIMESTAMP")).toBeVisible();
  await expect(details.getByRole("cell", { name: "2025-01-01" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "sales", pressed: true })).toBeVisible();
});

test("uploads a CSV file and shows what is in it", async ({ page }) => {
  await openApp(page);
  await page.getByLabel("Upload CSV").setInputFiles({
    name: "trips.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("city,km\nOslo,12\nLima,7\n"),
  });
  const details = page.getByRole("region", { name: "Details of trips" });
  await expect(details).toContainText("2 rows, 2 columns");
  await expect(details.getByRole("cell", { name: "Oslo" })).toBeVisible();
  await expect(page.getByRole("button", { name: "trips", pressed: true })).toBeVisible();
  await expectAccessible(page);
});
