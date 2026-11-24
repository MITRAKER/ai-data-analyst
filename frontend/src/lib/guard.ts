/**
 * Checks that keep other websites away from the web UI's server.
 *
 * The app runs on your own computer, and any website you visit runs code in
 * the same browser. Two tricks would let such a site use the app through it:
 *
 * - A cross-site request: the other site's page sends a form or a fetch() to
 *   http://localhost:3000. The browser sends it, although the page can't read
 *   the answer. That would be enough to replace a dataset with fake numbers,
 *   or to run the agent on your API credits. The browser names the sender in
 *   the `Sec-Fetch-Site` and `Origin` headers, so the server can refuse it.
 * - DNS rebinding: the other site points its own name at 127.0.0.1 after its
 *   page has loaded. The browser then treats the app as part of that site,
 *   and the page could read your data. But each request still names the other
 *   site in its `Host` header, so the server refuses names it doesn't know.
 */

import { errorResponse } from "@/lib/backend";

/** The host names the server always answers to: this computer's own. */
const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

/** A host name, or an IPv6 address in brackets, and an optional port. */
const HOST_HEADER = /^(\[[0-9a-f:.]+\]|[a-z0-9._-]+)(?::\d{1,5})?$/i;

/** The name in a Host header, without the port: "localhost:3000" -> "localhost". */
export function hostName(host: string): string | null {
  return HOST_HEADER.exec(host)?.[1]?.toLowerCase() ?? null;
}

/**
 * The host names the server answers to: this computer's own, and the
 * comma-separated names in ALLOWED_HOSTS (for example, a server's own name).
 */
export function allowedHosts(setting = process.env.ALLOWED_HOSTS ?? ""): Set<string> {
  const extra = setting
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter((name) => name !== "");
  return new Set([...LOCAL_HOSTS, ...extra]);
}

/**
 * Refuse a request for a host name that this server doesn't serve.
 *
 * @returns null if the name is allowed, or the error response to send.
 */
export function checkHost(request: Request): Response | null {
  const name = hostName(request.headers.get("host") ?? "");
  if (name !== null && allowedHosts().has(name)) {
    return null;
  }
  return errorResponse(
    421,
    "This server only answers to localhost. To use another name, add it to ALLOWED_HOSTS.",
  );
}

/**
 * Refuse a request that another website sent through the user's browser.
 * Every route that changes something (a POST) calls this.
 *
 * Browsers send `Sec-Fetch-Site` with every request, and `Origin` with every
 * POST. Tools such as curl send neither, so they pass: they don't run inside a
 * browser where another site's page could use them.
 *
 * @returns null if the request comes from the app's own page, or the error response to send.
 */
export function checkSameOrigin(request: Request): Response | null {
  const site = request.headers.get("sec-fetch-site");
  const origin = request.headers.get("origin");
  const host = request.headers.get("host")?.toLowerCase();
  const fromOtherSite =
    (site !== null && site !== "same-origin") ||
    (origin !== null && (!URL.canParse(origin) || new URL(origin).host !== host));
  return fromOtherSite ? errorResponse(403, "Requests from other websites are not allowed.") : null;
}

/** Every check for a request that only reads: the host name must be known. */
export function checkRead(request: Request): Response | null {
  return checkHost(request);
}

/** Every check for a request that changes something: a known host, sent by the app's own page. */
export function checkWrite(request: Request): Response | null {
  return checkHost(request) ?? checkSameOrigin(request);
}

/**
 * Refuse a body that is not JSON.
 *
 * A browser sends a JSON body to another site only after asking that site's
 * permission first (a "preflight" request), which this server never gives.
 * Plain text and form bodies don't need that permission, so they are refused.
 */
export function checkJson(request: Request): Response | null {
  const type = request.headers.get("content-type") ?? "";
  const mediaType = type.split(";", 1)[0]?.trim().toLowerCase();
  return mediaType === "application/json"
    ? null
    : errorResponse(415, "The question must be sent as JSON.");
}
