import { describe, expect, it } from "vitest";

import { isChart, parseAgentEvent } from "@/lib/events";
import { isObject, isRows, isStringArray } from "@/lib/json";
import { CHART, RUN } from "@/test/fakes";

describe("parseAgentEvent", () => {
  it("accepts every event of a real run", () => {
    const parsed = RUN.map(parseAgentEvent);
    expect(parsed.map((event) => event?.type)).toEqual([
      "thinking",
      "tool_call",
      "tool_result",
      "tool_call",
      "tool_result",
      "answer",
    ]);
  });

  it("renames is_error to isError and keeps the chart", () => {
    expect(parseAgentEvent(RUN[4])).toEqual({
      type: "tool_result",
      id: "t2",
      name: "make_chart",
      isError: false,
      content: "Chart created.",
      display: {},
      chart: CHART,
    });
  });

  it("accepts notes and errors", () => {
    expect(parseAgentEvent({ type: "note", text: "hi" })).toEqual({ type: "note", text: "hi" });
    expect(parseAgentEvent({ type: "error", message: "no", charts: [] })).toEqual({
      type: "error",
      message: "no",
      charts: [],
    });
  });

  it.each([
    ["not an object", "answer"],
    ["an array", []],
    ["no type", { text: "hi" }],
    ["an unknown type", { type: "debug", text: "hi" }],
    ["text that is not a string", { type: "note", text: 3 }],
    ["a tool call without input", { type: "tool_call", id: "t1", name: "x" }],
    ["a tool call with a numeric id", { type: "tool_call", id: 1, name: "x", input: {} }],
    ["a tool result without display", { ...RUN[2], display: null }],
    ["a tool result with a broken chart", { ...RUN[4], chart: { data: "x", layout: {} } }],
    ["a tool result with a string is_error", { ...RUN[2], is_error: "no" }],
    ["an answer with a broken chart list", { type: "answer", text: "x", charts: [{}] }],
    ["an answer without text", { type: "answer", charts: [] }],
    ["an error without a message", { type: "error", charts: [] }],
    ["an error whose charts are not a list", { type: "error", message: "x", charts: {} }],
  ])("rejects %s", (_label, value) => {
    expect(parseAgentEvent(value)).toBeNull();
  });
});

describe("JSON checks", () => {
  it("tells objects, string lists, rows and charts apart", () => {
    expect(isObject({})).toBe(true);
    expect(isObject(null)).toBe(false);
    expect(isObject([])).toBe(false);
    expect(isStringArray(["a", "b"])).toBe(true);
    expect(isStringArray(["a", 1])).toBe(false);
    expect(isStringArray("a")).toBe(false);
    expect(isRows([[1], []])).toBe(true);
    expect(isRows([1])).toBe(false);
    expect(isChart(CHART)).toBe(true);
    expect(isChart({ data: [1], layout: {} })).toBe(false);
    expect(isChart({ data: [], layout: [] })).toBe(false);
  });
});
