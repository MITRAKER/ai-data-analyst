// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import {
  backendUrl,
  checkLength,
  CLIENT_CLOSED,
  DEFAULT_BACKEND_URL,
  forward,
  UNREACHABLE,
} from "@/lib/backend";

function fakeFetch(result: Response | Error) {
  const fetch = vi.fn((_url: URL, _init?: RequestInit) =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("backendUrl", () => {
  it("uses BACKEND_URL, or the local default", () => {
    vi.stubEnv("BACKEND_URL", "http://api:8000");
    expect(backendUrl("/datasets").href).toBe("http://api:8000/datasets");
    vi.stubEnv("BACKEND_URL", undefined);
    expect(backendUrl("/health").href).toBe(`${DEFAULT_BACKEND_URL}/health`);
  });
});

describe("checkLength", () => {
  function request(length?: string) {
    const headers: Record<string, string> =
      length === undefined ? {} : { "content-length": length };
    return new Request("http://ui/api/ask", { method: "POST", headers });
  }

  it("accepts a body within the limit", () => {
    expect(checkLength(request("100"), 100, "too big")).toBeNull();
  });

  it("refuses a body that is too large, or of unknown size", async () => {
    const tooLarge = checkLength(request("101"), 100, "too big");
    expect(tooLarge?.status).toBe(413);
    expect(await tooLarge?.json()).toEqual({ detail: "too big" });
    expect(checkLength(request(), 100, "too big")?.status).toBe(411);
    expect(checkLength(request("abc"), 100, "too big")?.status).toBe(411);
    expect(checkLength(request("0"), 100, "too big")?.status).toBe(411);
  });
});

describe("forward", () => {
  it("passes the response on, with only the headers the browser needs", async () => {
    const upstream = new Response("data", {
      status: 201,
      headers: { "content-type": "text/csv", "set-cookie": "a=b", server: "uvicorn" },
    });
    const fetch = fakeFetch(upstream);
    const response = await forward("/datasets", { method: "POST" });
    expect(response.status).toBe(201);
    expect(await response.text()).toBe("data");
    expect(response.headers.get("content-type")).toBe("text/csv");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("server")).toBeNull();
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url?.pathname).toBe("/datasets");
    expect(init).toMatchObject({ method: "POST", cache: "no-store", redirect: "error" });
  });

  it("answers 502 when the API can't be reached", async () => {
    fakeFetch(new TypeError("fetch failed"));
    const response = await forward("/datasets");
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: UNREACHABLE });
  });

  it("gives up quietly when the browser has gone", async () => {
    const controller = new AbortController();
    controller.abort();
    fakeFetch(new DOMException("aborted", "AbortError"));
    const response = await forward("/ask/stream", { signal: controller.signal });
    expect(response.status).toBe(CLIENT_CLOSED);
  });
});
