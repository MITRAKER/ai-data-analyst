/**
 * Runs before every page request (Next.js calls this file "proxy").
 *
 * It creates a fresh random nonce for each request and puts it in the page's
 * Content-Security-Policy header. Next.js reads the nonce from that header and
 * adds it to its own <script> tags, so they run; any other script doesn't.
 */

import { NextResponse, type NextRequest } from "next/server";

import { contentSecurityPolicy } from "@/lib/csp";

export function proxy(request: NextRequest): NextResponse {
  const nonce = btoa(crypto.randomUUID());
  const policy = contentSecurityPolicy(nonce, process.env.NODE_ENV === "development");
  // Next.js reads the policy from the request, to find the nonce...
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  // ...and the browser reads it from the response.
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: not the API routes, and not the static files.
      source: "/((?!api|_next/static|_next/image|favicon.ico|icon.svg).*)",
      // Prefetches don't run scripts, so they need no nonce.
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
