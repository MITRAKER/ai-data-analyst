/**
 * The web UI's server forwards the browser's requests to the Python API.
 *
 * Only this server talks to the API; the browser never does. So the API can
 * stay on a private network (in Docker Compose it publishes no port at all)
 * and needs no CORS settings. The routes in src/app/api/ forward only the few
 * calls the UI needs, and nothing else.
 */

/** Where the Python API runs when BACKEND_URL is not set: `make run` on this computer. */
export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export const UNREACHABLE = "The analysis server is not reachable. Is it running?";

/**
 * The status for a request the browser cancelled ("Client Closed Request", as
 * nginx calls it). Nobody receives this answer; it only shows in logs.
 */
export const CLIENT_CLOSED = 499;

/** Headers of the API's response that the browser gets too. All others are dropped. */
const PASSED_ON = ["content-type", "cache-control", "x-accel-buffering"] as const;

/**
 * The full URL of an API path, such as "/datasets".
 *
 * @throws RangeError if the URL would point somewhere else than `path`, as
 *   "/datasets/.." (the root) does. That is a bug in a route, so it is not
 *   turned into an error response.
 */
export function backendUrl(path: string): URL {
  const url = new URL(path, process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL);
  if (url.pathname !== path) {
    throw new RangeError(`Not a plain API path: ${path}`);
  }
  return url;
}

/** A JSON error in the same shape as the API's own errors: {"detail": "..."}. */
export function errorResponse(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

/**
 * The size of a request body, checked before anything is forwarded.
 *
 * @returns null if the body is small enough, or the error response to send.
 */
export function checkLength(request: Request, maxBytes: number, tooLarge: string): Response | null {
  const length = Number(request.headers.get("content-length") ?? "");
  if (!Number.isInteger(length) || length <= 0) {
    return errorResponse(411, "The request needs a Content-Length header.");
  }
  return length > maxBytes ? errorResponse(413, tooLarge) : null;
}

/**
 * Send a request to the API and pass its response on.
 *
 * The response body is passed on as a stream, not read first, so each step
 * of an answer reaches the browser as soon as the API sends it.
 */
export async function forward(path: string, init: RequestInit = {}): Promise<Response> {
  // Outside the try: a bad path is a bug, not an API that can't be reached.
  const url = backendUrl(path);
  let upstream: Response;
  try {
    upstream = await fetch(url, { ...init, cache: "no-store", redirect: "error" });
  } catch {
    // If the browser cancelled its request, the fetch fails on purpose. Throwing
    // here would log an error for something normal, such as a closed page.
    if (init.signal?.aborted === true) {
      return errorResponse(CLIENT_CLOSED, "The browser cancelled the request.");
    }
    return errorResponse(502, UNREACHABLE);
  }
  const headers = new Headers();
  for (const name of PASSED_ON) {
    const value = upstream.headers.get(name);
    if (value !== null) {
      headers.set(name, value);
    }
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
