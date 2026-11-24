// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { GET as agentStatus } from "@/app/api/agent/status/route";
import { POST as ask } from "@/app/api/ask/route";
import { GET as dataset } from "@/app/api/datasets/[name]/route";
import { GET as datasets, POST as upload } from "@/app/api/datasets/route";
import { GET as health } from "@/app/api/health/route";
import { MAX_UPLOAD_BYTES } from "@/lib/api";
import { json, sse, streamOf } from "@/test/fakes";

function fakeFetch(response: Response) {
  const fetch = vi.fn((_url: URL, _init?: RequestInit) => Promise.resolve(response));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function called(fetch: ReturnType<typeof fakeFetch>) {
  const [url, init] = fetch.mock.calls[0] ?? [];
  return { path: url?.pathname, init };
}

function post(path: string, body: string, headers: Record<string, string> = {}) {
  return new Request(`http://ui${path}`, {
    method: "POST",
    body,
    headers: { "content-length": String(new TextEncoder().encode(body).length), ...headers },
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
    expect(await (await datasets(new Request("http://ui/api/datasets"))).json()).toEqual({
      datasets: ["sales"],
    });
    expect(called(fetch).path).toBe("/datasets");
    const status = fakeFetch(json({ ready: true, detail: "" }));
    await agentStatus(new Request("http://ui/api/agent/status"));
    expect(called(status).path).toBe("/agent/status");
  });

  it("escapes the dataset name, so it can't reach another path", async () => {
    const fetch = fakeFetch(json({}));
    const context = { params: Promise.resolve({ name: "../query" }) };
    await dataset(new Request("http://ui/api/datasets/x"), context);
    expect(called(fetch).path).toBe("/datasets/..%2Fquery");
  });

  it('answers "unknown dataset" for "." and "..", which would reach another path', async () => {
    const fetch = fakeFetch(json({}));
    for (const name of [".", ".."]) {
      const context = { params: Promise.resolve({ name }) };
      const response = await dataset(new Request("http://ui/api/datasets/x"), context);
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
    const request = new Request("http://ui/api/datasets", {
      method: "POST",
      headers: { "content-length": String(MAX_UPLOAD_BYTES * 2) },
    });
    const response = await upload(request);
    expect(response.status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();
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

  it("refuses a question that is too long", async () => {
    const fetch = fakeFetch(json({}));
    const response = await ask(post("/api/ask", "x".repeat(70_000)));
    expect(response.status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();
  });
});
