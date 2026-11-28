import AxeBuilder from "@axe-core/playwright";
import { expect, test as base, type Page } from "@playwright/test";

export { expect };

/** The fake API's address (see playwright.config.ts). */
export const FAKE_API = "http://127.0.0.1:8100";

/** A question the empty chat suggests (SUGGESTIONS in src/components/ConversationView.tsx). */
export const SUGGESTION = "Which region brought in the most revenue?";

/**
 * Playwright's `test`, with one addition: a test fails if the page logs an
 * error. That includes a script or a style that the Content-Security-Policy
 * blocked, and an error that React only reports in the console.
 *
 * The browser also logs each response with an error status, such as 404. A
 * test that expects some, sets them with `test.use({ expectedStatuses: [404] })`.
 */
export const test = base.extend<{ consoleErrors: string[]; expectedStatuses: number[] }>({
  expectedStatuses: [[], { option: true }],
  consoleErrors: [
    async ({ page, expectedStatuses }, provide) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") {
          errors.push(message.text());
        }
      });
      page.on("pageerror", (error) => {
        errors.push(error.message);
      });
      await provide(errors);
      const expected = expectedStatuses.map(
        (status) => `the server responded with a status of ${String(status)} `,
      );
      const unexpected = errors.filter((error) => !expected.some((note) => error.includes(note)));
      expect(unexpected, "errors in the browser console").toEqual([]);
    },
    { auto: true },
  ],
});

/**
 * Check the page with axe, the accessibility checker, against the WCAG 2.2
 * rules of levels A and AA: contrast, labels, roles, keyboard access and more.
 */
export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const problems = results.violations.map((violation) => {
    const where = violation.nodes.map((node) => node.target.join(" ")).join(", ");
    return `${violation.id} (${violation.help}): ${where}`;
  });
  expect(problems, "accessibility problems").toEqual([]);
}

/** Open the app and wait until a question can be asked. */
export async function openApp(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("button", { name: SUGGESTION })).toBeEnabled();
}
