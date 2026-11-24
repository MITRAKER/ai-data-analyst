import type { NextConfig } from "next";

// Security headers for every response. The pages' Content-Security-Policy is
// set per request in src/proxy.ts, because it carries a fresh nonce each time.
const securityHeaders = [
  // Browsers must not guess a file's type: a CSV is never run as a script.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Never tell other sites which page a link was clicked on.
  { key: "Referrer-Policy", value: "no-referrer" },
  // The app needs no camera, microphone or location.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // Other sites can't get a handle on this window through window.opener.
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  // Other sites can't show the app in a frame (older browsers; newer ones use
  // the CSP's frame-ancestors).
  { key: "X-Frame-Options", value: "DENY" },
];

// The API routes send JSON or events, never a page. So their policy allows
// nothing at all: no scripts, no styles, no frames.
const apiPolicy = {
  key: "Content-Security-Policy",
  value: "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
};

const nextConfig: NextConfig = {
  // Build a small, self-contained server for the Docker image.
  output: "standalone",
  // Don't announce "X-Powered-By: Next.js" to every visitor.
  poweredByHeader: false,
  reactStrictMode: true,
  headers: () =>
    Promise.resolve([
      { source: "/:path*", headers: securityHeaders },
      { source: "/api/:path*", headers: [apiPolicy] },
    ]),
};

export default nextConfig;
