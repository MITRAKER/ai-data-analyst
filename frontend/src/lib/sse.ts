/**
 * Server-Sent Events (SSE), read from a fetch() response.
 *
 * The server sends each step of the agent as soon as it happens, in this
 * plain-text format, with a blank line after each event:
 *
 *     event: tool_call
 *     data: {"type": "tool_call", "id": "t1", ...}
 *
 *     : ping
 *
 * A line that starts with ":" is a comment. The server sends ": ping" while
 * the agent is busy, so that no proxy closes the quiet connection.
 *
 * Browsers have EventSource for this format, but it can only send GET
 * requests, and a question needs a POST with a JSON body. So we read the
 * response body ourselves and cut it into events with `SseParser`.
 */

/** One event: its name (the `event:` field) and its data. */
export interface SseMessage {
  event: string;
  data: string;
}

/** The longest event we accept. An answer with several charts is far smaller. */
export const MAX_EVENT_CHARS = 5_000_000;

/** The longest stream we read. 12 steps with a chart each fit easily. */
export const MAX_STREAM_BYTES = 50_000_000;

export class StreamError extends Error {
  override name = "StreamError";
}

function parseBlock(block: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) {
      continue; // a comment, such as ": ping"
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") {
      event = value;
    } else if (field === "data") {
      data.push(value);
    }
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

/**
 * Cuts a stream of text into SSE messages.
 *
 * The text arrives in chunks of any size: one chunk can hold several events,
 * or only part of one. `push` returns the events that are complete, and keeps
 * the rest until the next chunk arrives.
 */
export class SseParser {
  private buffer = "";
  private pendingCR = false;

  push(chunk: string): SseMessage[] {
    // Lines may end with "\r\n", "\n" or "\r". A "\r" at the very end of a
    // chunk may be the first half of "\r\n", so it waits for the next chunk.
    let text = (this.pendingCR ? "\r" : "") + chunk;
    this.pendingCR = text.endsWith("\r");
    if (this.pendingCR) {
      text = text.slice(0, -1);
    }
    this.buffer += text.replace(/\r\n?/g, "\n");
    const blocks = this.buffer.split("\n\n");
    this.buffer = blocks.pop() ?? "";
    if (this.buffer.length > MAX_EVENT_CHARS) {
      throw new StreamError("An event from the server is too large.");
    }
    return blocks.map(parseBlock).filter((message) => message !== null);
  }

  /** The events still waiting when the stream ends. */
  finish(): SseMessage[] {
    const rest = this.pendingCR ? "\n" : ""; // a held-back "\r" ends a line after all
    this.pendingCR = false;
    return this.push(rest);
  }
}

/**
 * Read an SSE response body, one message at a time.
 *
 * @param maxBytes The most bytes to read. Tests pass a small number.
 * @throws StreamError If the stream is larger than `maxBytes`.
 */
export async function* readSse(
  body: ReadableStream<Uint8Array>,
  maxBytes = MAX_STREAM_BYTES,
): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    // Every read counts as at least one byte (even an empty one), so this
    // loop ends within `maxBytes` reads at the latest.
    for (let total = 0; total <= maxBytes;) {
      const { done, value } = await readChunk(reader);
      if (done) {
        // An event the stream cut off before its blank line is dropped, as
        // the SSE standard says.
        yield* parser.push(decoder.decode());
        yield* parser.finish();
        return;
      }
      total += Math.max(value.byteLength, 1);
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    throw new StreamError("The answer from the server is too large.");
  } finally {
    // Stop the download if the reader stops early, for example when the
    // user presses Stop. Cancelling a finished stream does nothing, and
    // cancelling a broken one only repeats the error that broke it.
    await reader.cancel().catch(() => undefined);
  }
}

/**
 * The next chunk of the body. If the connection breaks during the answer, the
 * browser only says "TypeError: network error". The connection did work at
 * first, so the message says that it broke, not that the server can't be found.
 */
async function readChunk(
  reader: ReadableStreamDefaultReader<Uint8Array>,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  try {
    return await reader.read();
  } catch {
    throw new StreamError("The connection broke during the answer. Please try again.");
  }
}
