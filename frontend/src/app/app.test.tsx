import { describe, expect, it, vi } from "vitest";

import RootLayout, { metadata } from "@/app/layout";
import Home from "@/app/page";
import { AnalystApp } from "@/components/AnalystApp";

vi.mock("next/server", () => ({ connection: vi.fn(() => Promise.resolve()) }));

describe("the page", () => {
  it("renders the app, for each request", async () => {
    const { connection } = await import("next/server");
    const page = await Home();
    expect(page.type).toBe(AnalystApp);
    expect(connection).toHaveBeenCalledOnce();
  });

  it("is an English page with a title", () => {
    const html = RootLayout({ children: "content", params: Promise.resolve({}) });
    expect(html.props).toMatchObject({ lang: "en" });
    expect(metadata.title).toBe("AI Data Analyst");
  });
});
