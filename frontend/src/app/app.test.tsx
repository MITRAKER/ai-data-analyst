import { describe, expect, it, vi } from "vitest";

import RootLayout, { metadata } from "@/app/layout";
import Home from "@/app/page";
import { AnalystApp } from "@/components/AnalystApp";

vi.mock("next/server", () => ({ connection: vi.fn(() => Promise.resolve()) }));

describe("the page", () => {
  it("renders the app", () => {
    expect(Home().type).toBe(AnalystApp);
  });

  it("is an English page with a title, rendered for each request", async () => {
    const { connection } = await import("next/server");
    const html = await RootLayout({ children: "content", params: Promise.resolve({}) });
    expect(html.props).toMatchObject({ lang: "en" });
    expect(metadata.title).toBe("AI Data Analyst");
    // Waiting for the request makes Next.js render every page per request,
    // so each one gets the fresh nonce.
    expect(connection).toHaveBeenCalledOnce();
  });
});
