// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { GET as agentStatus } from "@/app/api/agent/status/route";
import { POST as ask } from "@/app/api/ask/route";
import { GET as dataset } from "@/app/api/datasets/[name]/route";
import { GET as datasets, POST as upload } from "@/app/api/datasets/route";
import { GET as health } from "@/app/api/health/route";
import { MAX_UPLOAD_BYTES } from "@/lib/api";
import { json, sse, sseResponse, streamOf } from "@/test/fakes";

function fakeFetch(response: Response) {
  const fetch = vi.fn((_url: URL, _init?: RequestInit) => Promise.resolve(response));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function called(fetch: ReturnType<typeof fakeFetch>) {
  const [url, init] = fetch.mock.calls[0] ?? [];
  return { path: url?.pathname, init };
}

/** The headers a browser sends with a request from the app's own page. */
const SAME_ORIGIN = {
  host: "localhost:3000",
  origin: "http://localhost:3000",
  "sec-fetch-site": "same-origin",
};

function get(path: string) {
  return new Request(`http://localhost:3000${path}`, { headers: { host: "localhost:3000" } });
}

function post(path: string, body: string, headers: Record<string, string> = {}) {
  return new Request(`http://localhost:3000${path}`, {
    method: "POST",
    body,
    headers: {
      ...SAME_ORIGIN,
      "content-type": "application/json",
      "content-length": String(new TextEncoder().encode(body).length),
      ...headers,
    },
  });
}

describe("GET routes", () => {
  it("answers its own health check without calling the API", async () => {
    const fetch = fakeFetch(json({}));
    expect(await health().json()).toEqual({ status: "ok" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards the list of datasets and the agent's status", async () => {
    const fetch = fakeFetch(json({ datasets: ["sales"] }));
    expect(await (await datasets(get("/api/datasets"))).json()).toEqual({
      datasets: ["sales"],
    });
    expect(called(fetch).path).toBe("/datasets");
    const status = fakeFetch(json({ ready: true, detail: "" }));
    await agentStatus(get("/api/agent/status"));
    expect(called(status).path).toBe("/agent/status");
  });

  it("escapes the dataset name, so it can't reach another path", async () => {
    const fetch = fakeFetch(json({}));
    const context = { params: Promise.resolve({ name: "../query" }) };
    await dataset(get("/api/datasets/x"), context);
    expect(called(fetch).path).toBe("/datasets/..%2Fquery");
  });

  it('answers "unknown dataset" for "." and "..", which would reach another path', async () => {
    const fetch = fakeFetch(json({}));
    for (const name of [".", ".."]) {
      const context = { params: Promise.resolve({ name }) };
      const response = await dataset(get("/api/datasets/x"), context);
      expect(response.status).toBe(404);
      expect(await response.json()).toEqual({ detail: `Unknown dataset: ${name}` });
    }
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("POST /api/datasets", () => {
  it("streams the upload to the API with its form header", async () => {
    const fetch = fakeFetch(json({ name: "sales" }, 201));
    const response = await upload(
      post("/api/datasets", "--x\r\n...", { "content-type": "multipart/form-data; boundary=x" }),
    );
    expect(response.status).toBe(201);
    const { path, init } = called(fetch);
    expect(path).toBe("/datasets");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("content-type")).toBe("multipart/form-data; boundary=x");
    expect(init?.body).toBeInstanceOf(ReadableStream);
  });

  it("refuses a file that is too large before forwarding anything", async () => {
    const fetch = fakeFetch(json({}));
    const request = new Request("http://localhost:3000/api/datasets", {
      method: "POST",
      headers: { ...SAME_ORIGIN, "content-length": String(MAX_UPLOAD_BYTES * 2) },
    });
    const response = await upload(request);
    expect(response.status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("requests from other websites, or for other host names", () => {
  it("are refused before anything is forwarded", async () => {
    const fetch = fakeFetch(json({}));
    const form = { "content-type": "multipart/form-data; boundary=x" };
    const crossSite = { origin: "https://evil.example", "sec-fetch-site": "cross-site" };
    const refused = [
      // Another site's page uploads a file, or asks a question.
      await upload(post("/api/datasets", "--x\r\n...", { ...form, ...crossSite })),
      await ask(post("/api/ask", '{"question":"Who?"}', crossSite)),
      // A form from a sandboxed page or a file has the origin "null".
      await ask(post("/api/ask", '{"question":"Who?"}', { origin: "null" })),
      // Another app on this computer is the same site, but not the same origin.
      await ask(post("/api/ask", "{}", { origin: "http://localhost:5173" })),
      await ask(post("/api/ask", "{}", { "sec-fetch-site": "same-site" })),
    ];
    expect(refused.map((response) => response.status)).toEqual([403, 403, 403, 403, 403]);
    expect(await refused[0]?.json()).toEqual({
      detail: "Requests from other websites are not allowed.",
    });
    // DNS rebinding: the request names the other site as its host.
    const elsewhere = { host: "evil.example:3000", origin: "http://evil.example:3000" };
    expect((await ask(post("/api/ask", "{}", elsewhere))).status).toBe(421);
    // Every route that reads checks the host name too.
    function rebound(path: string) {
      return new Request(`http://evil.example${path}`, { headers: { host: "evil.example" } });
    }
    const reads = [
      await datasets(rebound("/api/datasets")),
      await dataset(rebound("/api/datasets/sales"), { params: Promise.resolve({ name: "sales" }) }),
      await agentStatus(rebound("/api/agent/status")),
    ];
    expect(reads.map((response) => response.status)).toEqual([421, 421, 421]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("let tools such as curl through, which send no Origin", async () => {
    const fetch = fakeFetch(sseResponse({ type: "answer", text: "ok", charts: [] }));
    const curl = new Request("http://localhost:3000/api/ask", {
      method: "POST",
      body: '{"question":"Who?"}',
      headers: {
        host: "localhost:3000",
        "content-type": "application/json",
        "content-length": "19",
      },
    });
    expect((await ask(curl)).status).toBe(200);
    expect(fetch).toHaveBeenCalledOnce();
  });
});

describe("POST /api/ask", () => {
  it("streams the agent's events from the API", async () => {
    const events =
      sse({ type: "note", text: "hi" }) + sse({ type: "answer", text: "ok", charts: [] });
    const fetch = fakeFetch(
      new Response(streamOf(events), { headers: { "content-type": "text/event-stream" } }),
    );
    const response = await ask(post("/api/ask", '{"question":"Who?"}'));
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(await response.text()).toBe(events);
    const { path, init } = called(fetch);
    expect(path).toBe("/ask/stream");
    expect(init?.body).toBe('{"question":"Who?"}');
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("passes the API's refusal on", async () => {
    fakeFetch(json({ detail: "Agent unavailable" }, 503));
    const response = await ask(post("/api/ask", '{"question":"Who?"}'));
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ detail: "Agent unavailable" });
  });

  it("reports an empty answer from the API", async () => {
    fakeFetch(new Response(null, { status: 200 }));
    const response = await ask(post("/api/ask", '{"question":"Who?"}'));
    expect(response.status).toBe(502);
  });

  it("refuses a question that is not JSON, as an HTML form would send it", async () => {
    const fetch = fakeFetch(json({}));
    const response = await ask(post("/api/ask", "question=Who", { "content-type": "text/plain" }));
    expect(response.status).toBe(415);
    expect(fetch).not.toHaveBeenCalled();
    // A charset after the type is fine.
    const json8 = { "content-type": "application/json; charset=utf-8" };
    fakeFetch(sseResponse({ type: "answer", text: "ok", charts: [] }));
    expect((await ask(post("/api/ask", '{"question":"Who?"}', json8))).status).toBe(200);
  });

  it("refuses a question that is too long", async () => {
    const fetch = fakeFetch(json({}));
    const response = await ask(post("/api/ask", "x".repeat(70_000)));
    expect(response.status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();
  });
});
