// Helpers that build fake server responses for the tests.
import type { AgentEvent } from "@/lib/events";

const encoder = new TextEncoder();

/** A stream that delivers these chunks of text, then ends. */
export function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

/** One event in the format the API sends it. */
export function sse(event: AgentEvent | Record<string, unknown>): string {
  const name = typeof event.type === "string" ? event.type : "message";
  return `event: ${name}\ndata: ${JSON.stringify(event)}\n\n`;
}

/** A server-sent-events response with these events. */
export function sseResponse(...events: (AgentEvent | Record<string, unknown>)[]): Response {
  return new Response(streamOf(...events.map(sse)), {
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** A stream that sends these events and then stays open until `signal` aborts. */
export function openStream(signal: AbortSignal, ...events: Record<string, unknown>[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(sse(event)));
      }
      signal.addEventListener("abort", () => {
        controller.error(new DOMException("The user aborted a request.", "AbortError"));
      });
    },
  });
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

/** A JSON response, like FastAPI's. */
export function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

// Events as the API sends them (snake_case, like backend/app/agent/events.py).
export const CHART = {
  data: [{ type: "bar", x: ["West", "East"], y: [572569.11, 545354.69] }],
  layout: { title: { text: "Revenue by region" }, xaxis: { title: { text: "region" } } },
};

export const RUN = [
  { type: "thinking", text: "I'll sum revenue by region." },
  {
    type: "tool_call",
    id: "t1",
    name: "query_database",
    input: {
      sql: "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY 1",
      purpose: "Totals",
    },
  },
  {
    type: "tool_result",
    id: "t1",
    name: "query_database",
    is_error: false,
    content: "{}",
    display: {
      result: {
        columns: ["region", "revenue"],
        rows: [
          ["West", 572569.11],
          ["East", 545354.69],
        ],
        row_count: 2,
        truncated: false,
      },
    },
    chart: null,
  },
  {
    type: "tool_call",
    id: "t2",
    name: "make_chart",
    input: { chart_type: "bar", title: "Revenue by region", sql: "SELECT 1" },
  },
  {
    type: "tool_result",
    id: "t2",
    name: "make_chart",
    is_error: false,
    content: "Chart created.",
    display: {},
    chart: CHART,
  },
  {
    type: "answer",
    text: "**West** sold the most.\n\n- East is second.",
    charts: [CHART],
    steps: 3,
  },
];
