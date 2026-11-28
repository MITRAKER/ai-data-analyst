import { randomUUID } from "node:crypto";

import { expect, expectAccessible, FAKE_API, openApp, SUGGESTION, test } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await openApp(page);
});

test("answers a question, and shows each step, the table and the chart", async ({ page }) => {
  await page.getByRole("button", { name: SUGGESTION }).click();

  await expect(page.getByText("the most revenue: 572,569.11.")).toBeVisible();
  await expect(page.locator("strong", { hasText: "West" })).toBeVisible();
  const chart = page.getByRole("figure", { name: "Revenue by region" });
  await expect(chart.locator(".main-svg").first()).toBeVisible(); // Plotly drew it

  // Once the answer is there, the steps fold away. Open them.
  await page.getByText("Show the 3 steps the agent took").click();
  await expect(page.getByText("Total revenue of each region")).toBeVisible();
  await expect(page.getByRole("cell", { name: "572569.11" })).toBeVisible();
  await expect(page.getByText("The chart is shown with the answer.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();
  await expectAccessible(page);
});

test("asks with the Enter key, and keeps earlier answers", async ({ page }) => {
  const box = page.getByRole("textbox", { name: "Your question" });
  await box.fill("Which region sold the most?");
  await box.press("Enter");
  await expect(page.getByText("the most revenue: 572,569.11.")).toBeVisible();
  await expect(box).toHaveValue("");

  await box.fill("And which one sold the least?");
  await box.press("Enter");
  const turns = page.getByRole("list", { name: "Questions and answers" }).locator(":scope > li");
  await expect(turns).toHaveCount(2);
  await expect(turns.nth(1).getByText("the most revenue: 572,569.11.")).toBeVisible();
  await expect(turns.nth(0)).toContainText("Which region sold the most?");
});

test("stops an answer, and the API stops working on it too", async ({ page, request }) => {
  const question = `Please answer slowly (${randomUUID()})`;
  const box = page.getByRole("textbox", { name: "Your question" });
  await box.fill(question);
  await box.press("Enter");
  await expect(page.getByText("This one takes a while.")).toBeVisible();
  await expect(page.getByText("Working…")).toBeVisible();

  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Stopped. The agent did not finish this answer.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();
  // The web UI's server closed its stream from the API, so the agent stops.
  await expect
    .poll(async () => {
      const response = await request.get(`${FAKE_API}/test/closed`, { params: { question } });
      const body: unknown = await response.json();
      return body;
    })
    .toEqual({ closed: true });
});

test("never turns a chart's text into a link", async ({ page }) => {
  const box = page.getByRole("textbox", { name: "Your question" });
  await box.fill("Show me a chart with a link.");
  await box.press("Enter");
  await expect(page.getByText("Here is the chart.")).toBeVisible();
  const chart = page.getByRole("figure").first();
  await expect(chart.locator(".main-svg").first()).toBeVisible(); // Plotly drew it
  // The text shows as it was written, tags and all, and nothing can be clicked.
  await expect(chart.getByText("Sign in again</a>").first()).toBeVisible();
  await expect(chart.locator("svg a")).toHaveCount(0);
});

test("shows why the agent could not answer", async ({ page }) => {
  const box = page.getByRole("textbox", { name: "Your question" });
  await box.fill("This question will fail.");
  await box.press("Enter");
  await expect(page.getByText("The agent stopped after 12 steps without an answer.")).toBeVisible();
  await page.getByText("Show the step the agent took").click();
  await expect(page.getByText("Let me look at the data first.")).toBeVisible();
  await expectAccessible(page);
});
