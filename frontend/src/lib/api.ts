/**
 * The browser's calls to the web UI's own server.
 *
 * The browser only ever talks to the server it loaded the page from. That
 * server (src/app/api/) forwards each call to the Python API. Every response
 * is checked here before the UI uses it.
 */

import { parseAgentEvent, type AgentEvent } from "@/lib/events";
import { isObject, isRows, isStringArray } from "@/lib/json";
import { readSse, StreamError } from "@/lib/sse";

export interface Column {
  name: string;
  type: string;
}

export interface DatasetInfo {
  name: string;
  rowCount: number;
  columns: Column[];
  sample: unknown[][];
}

export interface AgentStatus {
  ready: boolean;
  detail: string;
}

/** The largest CSV file the server accepts (MAX_UPLOAD_BYTES in backend/app/datastore.py). */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/** A request that failed, with a message for the user. */
export class ApiError extends Error {
  override name = "ApiError";
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** The message in a FastAPI error body: {"detail": "..."} or a list of problems. */
function detailOf(body: unknown): string | null {
  if (!isObject(body)) {
    return null;
  }
  const { detail } = body;
  if (typeof detail === "string") {
    return detail;
  }
  if (!Array.isArray(detail)) {
    return null;
  }
  const messages = detail
    .map((problem) => (isObject(problem) && typeof problem.msg === "string" ? problem.msg : ""))
    .filter((message) => message !== "");
  return messages.length > 0 ? messages.join(" ") : null;
}

async function failure(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null); // the body may not be JSON
  const fallback = `The server answered with an error (${String(response.status)}).`;
  return new ApiError(detailOf(body) ?? fallback, response.status);
}

function unexpected(what: string): ApiError {
  return new ApiError(`The server sent ${what} in an unexpected format.`, 502);
}

async function fetchJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw await failure(response);
  }
  return response.json();
}

function parseColumns(value: unknown): Column[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const columns: Column[] = [];
  for (const item of value) {
    if (!isObject(item) || typeof item.name !== "string" || typeof item.type !== "string") {
      return null;
    }
    columns.push({ name: item.name, type: item.type });
  }
  return columns;
}

export function parseDatasetInfo(value: unknown): DatasetInfo {
  if (isObject(value)) {
    const { name, row_count: rowCount, sample } = value;
    const columns = parseColumns(value.columns);
    if (typeof name === "string" && typeof rowCount === "number" && columns && isRows(sample)) {
      return { name, rowCount, columns, sample };
    }
  }
  throw unexpected("dataset details");
}

/** The names of all uploaded datasets. */
export async function listDatasets(): Promise<string[]> {
  const body = await fetchJson("/api/datasets");
  if (isObject(body) && isStringArray(body.datasets)) {
    return body.datasets;
  }
  throw unexpected("the list of datasets");
}

/** One dataset's columns, row count and first rows. */
export async function getDataset(name: string): Promise<DatasetInfo> {
  return parseDatasetInfo(await fetchJson(`/api/datasets/${encodeURIComponent(name)}`));
}

/** Upload a CSV file. The server turns it into a table and describes it. */
export async function uploadDataset(file: File): Promise<DatasetInfo> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new ApiError("The file is larger than 50 MB.", 413);
  }
  const form = new FormData();
  form.append("file", file);
  return parseDatasetInfo(await fetchJson("/api/datasets", { method: "POST", body: form }));
}

/** Can the agent answer questions? If not, `detail` says why (for example, no API key). */
export async function getAgentStatus(): Promise<AgentStatus> {
  const body = await fetchJson("/api/agent/status");
  if (isObject(body) && typeof body.ready === "boolean" && typeof body.detail === "string") {
    return { ready: body.ready, detail: body.detail };
  }
  throw unexpected("the agent's status");
}

/**
 * Ask the agent a question, and get each of its steps as soon as it happens.
 *
 * This is an async generator: `for await (const event of askQuestion(...))`
 * receives the events one by one, while the agent is still working. The
 * backend's agent is a generator too (backend/app/agent/orchestrator.py), so
 * the same idea runs from Python all the way to the screen.
 *
 * @param signal Abort it to stop: the request is cancelled, and the server
 *     stops the agent after the step it is on.
 */
export async function* askQuestion(
  question: string,
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!response.ok) {
    throw await failure(response);
  }
  if (response.body === null) {
    throw new StreamError("The server sent an empty answer.");
  }
  for await (const message of readSse(response.body)) {
    const event = parseAgentEvent(JSON.parse(message.data));
    if (event === null) {
      throw new StreamError(`The server sent an unexpected "${message.event}" event.`);
    }
    yield event;
  }
}
