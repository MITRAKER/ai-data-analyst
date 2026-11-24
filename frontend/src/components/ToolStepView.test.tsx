import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MAX_OUTPUT_CHARS, ToolStepView } from "@/components/ToolStepView";
import type { ToolStep } from "@/lib/conversation";
import type { ToolResultEvent } from "@/lib/events";
import { CHART } from "@/test/fakes";

function result(extra: Partial<ToolResultEvent>): ToolResultEvent {
  return {
    type: "tool_result",
    id: "t1",
    name: "run_python",
    isError: false,
    content: "",
    display: {},
    chart: null,
    ...extra,
  };
}

function show(step: Partial<ToolStep>) {
  const full: ToolStep = { kind: "tool", id: "t1", name: "run_python", input: {}, result: null };
  render(
    <ol>
      <ToolStepView step={{ ...full, ...step }} />
    </ol>,
  );
}

describe("ToolStepView", () => {
  it("shows the code and the purpose while the tool runs", () => {
    show({ input: { sql: "SELECT 1", code: "print(df)", purpose: "A check" } });
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("A check")).toBeInTheDocument();
    expect(screen.getByText("SELECT 1")).toBeInTheDocument();
    expect(screen.getByText("print(df)")).toBeInTheDocument();
    expect(screen.getByText("Running…")).toBeInTheDocument();
  });

  it("shows a chart's title, and where the chart is", () => {
    show({ name: "make_chart", input: { title: "Revenue" }, result: result({ chart: CHART }) });
    expect(screen.getByText("Chart")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("The chart is shown with the answer.")).toBeInTheDocument();
  });

  it("shows what Python printed, or that it printed nothing", () => {
    show({ result: result({ display: { ok: true, stdout: "42\n", error: null } }) });
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("says when Python printed nothing", () => {
    show({ result: result({ display: { ok: true, stdout: "", error: null } }) });
    expect(screen.getByText("(no output)")).toBeInTheDocument();
  });

  it("shows errors, cut to a readable length", () => {
    const long = "E".repeat(MAX_OUTPUT_CHARS + 10);
    show({ result: result({ isError: true, content: long }) });
    expect(document.querySelector("pre")?.textContent).toBe(`${"E".repeat(MAX_OUTPUT_CHARS)}\n…`);
  });

  it("falls back to the text result for an unknown tool", () => {
    show({ name: "future_tool", result: result({ name: "future_tool", content: "done" }) });
    expect(screen.getByText("future_tool")).toBeInTheDocument();
    expect(screen.getByText("done")).toBeInTheDocument();
  });
});
