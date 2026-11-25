import { expect, expectAccessible, FAKE_API, openApp, SUGGESTION, test } from "./fixtures";

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

test.describe("pages and requests that fail on purpose", () => {
  // The browser logs each of these responses in the console.
  test.use({ expectedStatuses: [403, 404] });

  test("gives the page-not-found page a nonce too, so its scripts run", async ({ page }) => {
    // The test fails if the policy blocked a script: that logs an error.
    for (const path of ["/no-such-page", "/apix", "/_next/image/x"]) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(404);
      expect(response?.headers()["content-security-policy"]).toMatch(/'nonce-[\w+/=]+'/);
      await expect(page.getByText("This page could not be found.")).toBeVisible();
    }
  });

  test("refuses an upload that another website's page sends", async ({
    page,
    request,
    baseURL,
    consoleErrors,
  }) => {
    // The fake API's address is another origin, as another website would be.
    await page.goto(`${FAKE_API}/health`);
    await page.evaluate(async (url) => {
      const form = new FormData();
      form.append("file", new Blob(["city,km\nFake,1\n"], { type: "text/csv" }), "planted.csv");
      // "no-cors": the page can't read the answer, but the browser sends the
      // request all the same. That is how one site could use another.
      await fetch(url, { method: "POST", mode: "no-cors", body: form });
    }, new URL("/api/datasets", baseURL).href);
    // The browser did send it, and logged the server's refusal.
    await expect
      .poll(() => consoleErrors.some((error) => error.includes("status of 403 (Forbidden)")))
      .toBe(true);
    const response = await request.get("/api/datasets");
    expect(await response.json()).toEqual({ datasets: expect.not.arrayContaining(["planted"]) });
  });
});

test("allows nothing at all on the API's addresses", async ({ request }) => {
  for (const path of ["/api/health", "/api/no-such-route"]) {
    const response = await request.get(path);
    expect(response.headers()["content-security-policy"]).toBe(
      "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    );
  }
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
