/**
 * The events the agent sends while it works.
 *
 * These types mirror backend/app/agent/events.py: each step of the agent
 * (a thought, a note, a tool call, a tool result) is one event, and the last
 * event is always an answer or an error. The events arrive over the network,
 * so `parseAgentEvent` checks every field before the UI uses one.
 */

import { isObject, type JsonObject } from "@/lib/json";

/** A Plotly figure, as backend/app/agent/charts.py builds it. */
export interface Chart {
  data: JsonObject[];
  layout: JsonObject;
}

export interface ThinkingEvent {
  type: "thinking";
  text: string;
}

export interface NoteEvent {
  type: "note";
  text: string;
}

export interface ToolCallEvent {
  type: "tool_call";
  id: string;
  name: string;
  input: JsonObject;
}

export interface ToolResultEvent {
  type: "tool_result";
  id: string;
  name: string;
  isError: boolean;
  content: string;
  display: JsonObject;
  chart: Chart | null;
}

export interface AnswerEvent {
  type: "answer";
  text: string;
  charts: Chart[];
}

export interface RunErrorEvent {
  type: "error";
  message: string;
  charts: Chart[];
}

export type AgentEvent =
  ThinkingEvent | NoteEvent | ToolCallEvent | ToolResultEvent | AnswerEvent | RunErrorEvent;

export function isChart(value: unknown): value is Chart {
  return (
    isObject(value) &&
    Array.isArray(value.data) &&
    value.data.every(isObject) &&
    isObject(value.layout)
  );
}

function isChartList(value: unknown): value is Chart[] {
  return Array.isArray(value) && value.every(isChart);
}

function parseToolResult(value: JsonObject): ToolResultEvent | null {
  const { id, name, is_error: isError, content, display, chart } = value;
  const chartOk = chart === null || isChart(chart);
  if (
    typeof id !== "string" ||
    typeof name !== "string" ||
    typeof isError !== "boolean" ||
    typeof content !== "string" ||
    !isObject(display) ||
    !chartOk
  ) {
    return null;
  }
  return { type: "tool_result", id, name, isError, content, display, chart };
}

function parseToolCall(value: JsonObject): ToolCallEvent | null {
  const { id, name, input } = value;
  return typeof id === "string" && typeof name === "string" && isObject(input)
    ? { type: "tool_call", id, name, input }
    : null;
}

function parseAnswer(value: JsonObject): AnswerEvent | null {
  const { text, charts } = value;
  return typeof text === "string" && isChartList(charts) ? { type: "answer", text, charts } : null;
}

function parseRunError(value: JsonObject): RunErrorEvent | null {
  const { message, charts } = value;
  return typeof message === "string" && isChartList(charts)
    ? { type: "error", message, charts }
    : null;
}

/**
 * Check one event from the server.
 *
 * @returns The event, or null if it is not a valid agent event.
 */
export function parseAgentEvent(value: unknown): AgentEvent | null {
  if (!isObject(value)) {
    return null;
  }
  switch (value.type) {
    case "thinking":
    case "note":
      return typeof value.text === "string" ? { type: value.type, text: value.text } : null;
    case "tool_call":
      return parseToolCall(value);
    case "tool_result":
      return parseToolResult(value);
    case "answer":
      return parseAnswer(value);
    case "error":
      return parseRunError(value);
    default:
      return null;
  }
}
