import { describe, expect, it } from "vitest";

import { MAX_EVENT_CHARS, readSse, SseParser, StreamError } from "@/lib/sse";
import { streamOf } from "@/test/fakes";

async function collect(stream: ReadableStream<Uint8Array>, maxBytes?: number) {
  const messages = [];
  for await (const message of readSse(stream, maxBytes)) {
    messages.push(message);
  }
  return messages;
}

describe("SseParser", () => {
  it("returns only complete events, and keeps the rest for later", () => {
    const parser = new SseParser();
    expect(parser.push('event: note\ndata: {"a"')).toEqual([]);
    expect(parser.push(": 1}\n\nevent: answer\n")).toEqual([{ event: "note", data: '{"a": 1}' }]);
    expect(parser.push("data: x\n\n")).toEqual([{ event: "answer", data: "x" }]);
  });

  it("skips comments such as the server's keep-alive pings", () => {
    const parser = new SseParser();
    expect(parser.push(": ping\n\n:another\ndata: y\n\n")).toEqual([
      { event: "message", data: "y" },
    ]);
  });

  it("joins data lines and reads fields without a space or a value", () => {
    const parser = new SseParser();
    expect(parser.push("event:note\ndata:a\ndata\ndata: c\nid: 7\n\n")).toEqual([
      { event: "note", data: "a\n\nc" },
    ]);
  });

  it("accepts CRLF and CR line endings, even split between chunks", () => {
    const parser = new SseParser();
    expect(parser.push("data: one\r")).toEqual([]);
    expect(parser.push("\n\r\ndata: two\r\r")).toEqual([{ event: "message", data: "one" }]);
    expect(parser.push("")).toEqual([]);
    expect(parser.finish()).toEqual([{ event: "message", data: "two" }]);
    expect(parser.finish()).toEqual([]);
  });

  it("refuses an event that is too large", () => {
    const parser = new SseParser();
    expect(() => parser.push("data: " + "x".repeat(MAX_EVENT_CHARS))).toThrow(StreamError);
  });
});

describe("readSse", () => {
  it("reads events from a stream of bytes, however it is cut", async () => {
    const stream = streamOf("event: note\nda", "ta: é\n", "\nevent: answer\ndata: done\n\n");
    expect(await collect(stream)).toEqual([
      { event: "note", data: "é" },
      { event: "answer", data: "done" },
    ]);
  });

  it("decodes a character split across two chunks", async () => {
    const bytes = new TextEncoder().encode("data: é\n\n");
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 7)); // "data: " and half of "é"
        controller.enqueue(bytes.slice(7));
        controller.close();
      },
    });
    expect(await collect(stream)).toEqual([{ event: "message", data: "é" }]);
  });

  it("drops an event that the stream cut off", async () => {
    expect(await collect(streamOf("data: complete\n\ndata: cut off"))).toEqual([
      { event: "message", data: "complete" },
    ]);
  });

  it("refuses a stream that is too large, and stops downloading it", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.enqueue(new TextEncoder().encode(": ping\n\n")); // 8 bytes, forever
      },
      cancel() {
        cancelled = true;
      },
    });
    await expect(collect(stream, 100)).rejects.toThrow("The answer from the server is too large.");
    expect(cancelled).toBe(true);
  });

  it("counts an empty chunk as one byte, so empty chunks cannot go on forever", async () => {
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.enqueue(new Uint8Array(0));
      },
    });
    await expect(collect(stream, 10)).rejects.toBeInstanceOf(StreamError);
  });

  it("stops reading when the caller stops early", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.enqueue(new TextEncoder().encode("data: again\n\n"));
      },
      cancel() {
        cancelled = true;
      },
    });
    for await (const message of readSse(stream)) {
      expect(message.data).toBe("again");
      break;
    }
    expect(cancelled).toBe(true);
  });
});
