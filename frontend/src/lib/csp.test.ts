// @vitest-environment node
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { contentSecurityPolicy } from "@/lib/csp";
import { config, proxy } from "@/proxy";

describe("contentSecurityPolicy", () => {
  it("allows only scripts with the nonce, and nothing from other sites", () => {
    const policy = contentSecurityPolicy("abc123", false);
    expect(policy).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic';");
    expect(policy).toContain("default-src 'self'");
    expect(policy).toContain("connect-src 'self'");
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).not.toContain("unsafe-eval");
  });

  it("allows eval() in development only, for React's debugging tools", () => {
    expect(contentSecurityPolicy("n", true)).toContain("'strict-dynamic' 'unsafe-eval'");
  });
});

describe("proxy", () => {
  function nonceOf(policy: string | null): string {
    return /'nonce-([^']+)'/.exec(policy ?? "")?.[1] ?? "";
  }

  it("gives every page request a new nonce, for Next.js and for the browser", () => {
    const first = proxy(new NextRequest("http://localhost:3000/"));
    const second = proxy(new NextRequest("http://localhost:3000/"));
    const policy = first.headers.get("content-security-policy");
    expect(nonceOf(policy).length).toBeGreaterThanOrEqual(32);
    expect(nonceOf(policy)).not.toBe(nonceOf(second.headers.get("content-security-policy")));
    // Next.js reads the same policy from the request, to find the nonce.
    expect(first.headers.get("x-middleware-request-content-security-policy")).toBe(policy);
  });

  it("runs for pages only, not for the API or static files", () => {
    const [rule] = config.matcher;
    const pattern = new RegExp(`^${rule?.source ?? ""}$`);
    expect(pattern.test("/")).toBe(true);
    expect(pattern.test("/api/ask")).toBe(false);
    expect(pattern.test("/_next/static/chunk.js")).toBe(false);
  });
});
