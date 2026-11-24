/**
 * A stand-in for the Python API (backend/app/main.py), for the browser tests.
 *
 * It answers the same routes in the same format, with made-up data, so the
 * browser tests need neither Python nor a Claude API key. The browser still
 * goes through the web UI's own server (src/app/api/), as it does for real.
 *
 *     node e2e/fake-api.mts 8100
 *
 * Node.js runs this TypeScript file as it is: it drops the types and runs
 * the rest. (That is why it imports nothing from src/: Node.js can't resolve
 * the "@/" paths there.)
 *
 * Questions decide the answer:
 * - one that contains "slowly" gets an answer that never ends, so that a test
 *   can press Stop. Then GET /test/closed?question=... says whether the web
 *   UI's server closed the stream, which shows that Stop reached the API;
 * - one that contains "fail" ends with an error from the agent;
 * - any other question gets the same answer, with a table and a chart.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { text } from "node:stream/consumers";
import { setTimeout as sleep } from "node:timers/promises";

interface DatasetInfo {
  name: string;
  row_count: number;
  columns: { name: string; type: string }[];
  sample: unknown[][];
}

const SALES: DatasetInfo = {
  name: "sales",
  row_count: 2000,
  columns: [
    { name: "order_date", type: "TIMESTAMP" },
    { name: "region", type: "VARCHAR" },
    { name: "revenue", type: "DOUBLE" },
  ],
  sample: [
    ["2025-01-01T00:00:00", "West", 812.5],
    ["2025-01-01T00:00:00", "East", 640],
  ],
};

const TOTALS = [
  ["West", 572569.11],
  ["East", 545354.69],
  ["North", 498201.4],
  ["South", 476532.2],
];

const CHART = {
  data: [{ type: "bar", x: TOTALS.map((row) => row[0]), y: TOTALS.map((row) => row[1]) }],
  layout: {
    title: { text: "Revenue by region" },
    xaxis: { title: { text: "region" } },
    yaxis: { title: { text: "revenue" } },
  },
};

const SQL = "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region ORDER BY 2 DESC";

/** The events of one answer, as the API sends them (backend/app/agent/events.py). */
const ANSWER = [
  { type: "thinking", text: "I'll add up the revenue of each region." },
  {
    type: "tool_call",
    id: "t1",
    name: "query_database",
    input: { sql: SQL, purpose: "Total revenue of each region" },
  },
  {
    type: "tool_result",
    id: "t1",
    name: "query_database",
    is_error: false,
    content: JSON.stringify({ columns: ["region", "revenue"], rows: TOTALS }),
    display: {
      result: { columns: ["region", "revenue"], rows: TOTALS, row_count: 4, truncated: false },
    },
    chart: null,
  },
  {
    type: "tool_call",
    id: "t2",
    name: "make_chart",
    input: { sql: SQL, chart_type: "bar", x: "region", y: "revenue", title: "Revenue by region" },
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
    text: "**West** brought in the most revenue: 572,569.11.\n\n- East is second.\n- South is last.",
    charts: [CHART],
    steps: 3,
  },
];

/** Time between two steps, so that the steps arrive one by one. */
const STEP_DELAY_MS = 40;

/** How long a slow answer stays open at most, in ticks of 100 ms. */
const SLOW_TICKS = 300;

/** The datasets so far, by name. */
const datasets = new Map<string, DatasetInfo>([["sales", SALES]]);

/** Questions whose stream was closed before the answer ended. */
const closed = new Set<string>();

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

function sendEvent(
  response: ServerResponse,
  event: { type: string; [key: string]: unknown },
): void {
  response.write(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`);
}

/** POST /datasets: read the CSV file from the form, and keep its details. */
async function upload(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body = await text(request);
  const filename = /filename="([^"]*)"/.exec(body)?.[1] ?? "";
  if (!filename.toLowerCase().endsWith(".csv")) {
    sendJson(response, 400, { detail: "Please upload a .csv file." });
    return;
  }
  // The file comes after the first blank line, and ends at the next boundary.
  const start = body.indexOf("\r\n\r\n") + 4;
  const [header = "", ...rows] = body
    .slice(start, body.indexOf("\r\n--", start))
    .trim()
    .split(/\r?\n/);
  const info: DatasetInfo = {
    name: filename.slice(0, -4).toLowerCase().replace(/\W/g, "_"),
    row_count: rows.length,
    columns: header.split(",").map((name) => ({ name, type: "VARCHAR" })),
    sample: rows.slice(0, 5).map((row) => row.split(",")),
  };
  datasets.set(info.name, info);
  sendJson(response, 201, info);
}

/** GET /datasets/{name} */
function describe(response: ServerResponse, name: string): void {
  const info = datasets.get(name);
  if (info === undefined) {
    sendJson(response, 404, { detail: `Unknown dataset: ${name}` });
  } else {
    sendJson(response, 200, info);
  }
}

/** Send pings until the client leaves, as the API does while the agent works. */
async function answerSlowly(response: ServerResponse): Promise<void> {
  sendEvent(response, { type: "note", text: "This one takes a while." });
  for (let tick = 0; tick < SLOW_TICKS && !response.destroyed; tick += 1) {
    response.write(": ping\n\n");
    await sleep(100);
  }
}

/** POST /ask/stream */
async function ask(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body: unknown = JSON.parse(await text(request));
  const question =
    typeof body === "object" && body !== null && "question" in body ? String(body.question) : "";
  response.on("close", () => {
    if (!response.writableFinished) {
      closed.add(question);
    }
  });
  response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
  if (question.includes("slowly")) {
    await answerSlowly(response);
  } else if (question.includes("fail")) {
    sendEvent(response, { type: "note", text: "Let me look at the data first." });
    sendEvent(response, {
      type: "error",
      message: "The agent stopped after 12 steps without an answer.",
      charts: [],
    });
  } else {
    for (const event of ANSWER) {
      await sleep(STEP_DELAY_MS);
      sendEvent(response, event);
    }
  }
  if (!response.destroyed) {
    response.end();
  }
}

type Handler = (request: IncomingMessage, response: ServerResponse, url: URL) => unknown;

const ROUTES = new Map<string, Handler>([
  [
    "GET /health",
    (_request, response) => {
      sendJson(response, 200, { status: "ok" });
    },
  ],
  [
    "GET /datasets",
    (_request, response) => {
      sendJson(response, 200, { datasets: [...datasets.keys()].sort() });
    },
  ],
  ["POST /datasets", upload],
  [
    "GET /agent/status",
    (_request, response) => {
      sendJson(response, 200, { ready: true, detail: "" });
    },
  ],
  ["POST /ask/stream", ask],
  [
    "GET /test/closed",
    (_request, response, url) => {
      sendJson(response, 200, { closed: closed.has(url.searchParams.get("question") ?? "") });
    },
  ],
]);

async function handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const url = new URL(request.url ?? "/", "http://fake-api");
  const method = request.method ?? "GET";
  const handler = ROUTES.get(`${method} ${url.pathname}`);
  if (handler !== undefined) {
    await handler(request, response, url);
  } else if (method === "GET" && url.pathname.startsWith("/datasets/")) {
    describe(response, decodeURIComponent(url.pathname.slice("/datasets/".length)));
  } else {
    sendJson(response, 404, { detail: "Not Found" });
  }
}

const port = Number(process.argv[2] ?? "8100");
const server = createServer((request, response) => {
  handle(request, response).catch((error: unknown) => {
    console.error(error);
    if (response.headersSent) {
      response.destroy();
    } else {
      sendJson(response, 500, { detail: "The fake API failed." });
    }
  });
});
server.listen(port, "127.0.0.1", () => {
  console.log(`Fake API on http://127.0.0.1:${String(port)}`);
});
