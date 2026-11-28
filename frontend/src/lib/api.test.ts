import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  askQuestion,
  getAgentStatus,
  getDataset,
  listDatasets,
  MAX_UPLOAD_BYTES,
  parseDatasetInfo,
  uploadDataset,
} from "@/lib/api";
import { StreamError } from "@/lib/sse";
import { json, RUN, sse, sseResponse, streamOf } from "@/test/fakes";

const INFO = {
  name: "sales",
  row_count: 2000,
  columns: [{ name: "region", type: "VARCHAR" }],
  sample: [["West"]],
};

function fakeFetch(response: Response) {
  const fetch = vi.fn((_url: string, _init?: RequestInit) => Promise.resolve(response));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function collect(question: string) {
  const types = [];
  for await (const event of askQuestion(question, new AbortController().signal)) {
    types.push(event.type);
  }
  return types;
}

describe("dataset calls", () => {
  it("lists datasets", async () => {
    const fetch = fakeFetch(json({ datasets: ["sales"] }));
    expect(await listDatasets()).toEqual(["sales"]);
    expect(fetch).toHaveBeenCalledWith("/api/datasets", undefined);
  });

  it("gets one dataset, with its name escaped in the URL", async () => {
    const fetch = fakeFetch(json(INFO));
    expect(await getDataset("my data/2")).toEqual({
      ...INFO,
      rowCount: 2000,
      row_count: undefined,
    });
    expect(fetch).toHaveBeenCalledWith("/api/datasets/my%20data%2F2", undefined);
  });

  it("uploads a file as a form", async () => {
    const fetch = fakeFetch(json(INFO, 201));
    const file = new File(["a,b\n1,2\n"], "sales.csv", { type: "text/csv" });
    expect((await uploadDataset(file)).name).toBe("sales");
    const [, init] = fetch.mock.calls[0] ?? [];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
  });

  it("refuses a file that is too large without sending it", async () => {
    const fetch = fakeFetch(json(INFO));
    const big = new File(["x"], "big.csv");
    Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });
    await expect(uploadDataset(big)).rejects.toThrow("larger than 50 MB");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects responses in an unexpected shape", async () => {
    fakeFetch(json({ datasets: [1] }));
    await expect(listDatasets()).rejects.toThrow("the list of datasets");
    expect(() => parseDatasetInfo({ ...INFO, columns: [{ name: 1 }] })).toThrow(ApiError);
    expect(() => parseDatasetInfo({ ...INFO, columns: "x" })).toThrow(ApiError);
    expect(() => parseDatasetInfo(null)).toThrow(ApiError);
  });
});

describe("errors", () => {
  it("uses FastAPI's detail message", async () => {
    fakeFetch(json({ detail: "Please upload a .csv file." }, 400));
    await expect(listDatasets()).rejects.toMatchObject({
      name: "ApiError",
      message: "Please upload a .csv file.",
      status: 400,
    });
  });

  it("joins the messages of a validation error", async () => {
    fakeFetch(json({ detail: [{ msg: "too short" }, { msg: "bad" }, "odd"] }, 422));
    await expect(listDatasets()).rejects.toThrow("too short bad");
  });

  it.each([
    ["no detail", { error: "x" }],
    ["a detail list without messages", { detail: [{}] }],
    ["a detail of another type", { detail: 42 }],
    ["a body that is not an object", ["x"]],
  ])("falls back to the status for %s", async (_label, body) => {
    fakeFetch(json(body, 500));
    await expect(listDatasets()).rejects.toThrow("(500)");
  });

  it("falls back to the status when the body is not JSON", async () => {
    fakeFetch(new Response("Bad gateway", { status: 502 }));
    await expect(getAgentStatus()).rejects.toThrow("The server answered with an error (502).");
  });
});

describe("getAgentStatus", () => {
  it("returns whether the agent is ready, and why not", async () => {
    fakeFetch(json({ ready: false, detail: "ANTHROPIC_API_KEY is not set." }));
    expect(await getAgentStatus()).toEqual({
      ready: false,
      detail: "ANTHROPIC_API_KEY is not set.",
    });
  });

  it("rejects a status in the wrong shape", async () => {
    fakeFetch(json({ ready: "yes" }));
    await expect(getAgentStatus()).rejects.toThrow("the agent's status");
  });
});

describe("askQuestion", () => {
  it("posts the question and yields each event", async () => {
    const fetch = fakeFetch(sseResponse(...RUN));
    expect(await collect("Who sold most?")).toEqual([
      "thinking",
      "tool_call",
      "tool_result",
      "tool_call",
      "tool_result",
      "answer",
    ]);
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe("/api/ask");
    expect(init?.body).toBe(JSON.stringify({ question: "Who sold most?" }));
  });

  it("throws the API's message when the request is refused", async () => {
    fakeFetch(json({ detail: "Agent unavailable: ANTHROPIC_API_KEY is not set." }, 503));
    await expect(collect("hi?")).rejects.toThrow("Agent unavailable");
  });

  it("throws on an event it doesn't know", async () => {
    fakeFetch(new Response(streamOf(sse({ type: "mystery" }))));
    await expect(collect("hi?")).rejects.toThrow(StreamError);
  });

  it("throws when the response has no body", async () => {
    fakeFetch(new Response(null, { status: 200 }));
    await expect(collect("hi?")).rejects.toThrow("empty answer");
  });
});
