import { describe, expect, it } from "vitest";

import {
  applyEvent,
  conversationReducer,
  emptyConversation,
  ENDED_EARLY,
  MAX_STEPS_PER_TURN,
  MAX_TURNS,
  type Conversation,
  type ConversationAction,
} from "@/lib/conversation";
import { parseAgentEvent, type AgentEvent } from "@/lib/events";
import { CHART, RUN } from "@/test/fakes";

function events(): AgentEvent[] {
  return RUN.map((raw) => {
    const event = parseAgentEvent(raw);
    if (event === null) {
      throw new Error("bad test data");
    }
    return event;
  });
}

function run(actions: ConversationAction[], start: Conversation = emptyConversation) {
  return actions.reduce(conversationReducer, start);
}

const asked: ConversationAction = { type: "asked", id: 1, question: "Who sold most?" };

describe("conversationReducer", () => {
  it("builds a turn from a whole run", () => {
    const state = run([
      asked,
      ...events().map((event) => ({ type: "event" as const, id: 1, event })),
    ]);
    const [turn] = state.turns;
    expect(turn?.status).toBe("answered");
    expect(turn?.answer).toBe("**West** sold the most.\n\n- East is second.");
    expect(turn?.charts).toEqual([CHART]);
    // Each tool call and its result become one step.
    expect(turn?.steps.map((step) => step.kind)).toEqual(["thinking", "tool", "tool"]);
    const tool = turn?.steps[1];
    expect(tool?.kind === "tool" && tool.result?.id).toBe("t1");
  });

  it("never changes the state it was given", () => {
    const before = run([asked]);
    const frozen = JSON.stringify(before);
    run([{ type: "event", id: 1, event: { type: "note", text: "x" } }], before);
    expect(JSON.stringify(before)).toBe(frozen);
  });

  it("marks a question failed when the stream ends without an answer", () => {
    const [turn] = run([asked, { type: "ended", id: 1 }]).turns;
    expect(turn?.status).toBe("failed");
    expect(turn?.error).toBe(ENDED_EARLY);
  });

  it("ignores the end of the stream after the answer", () => {
    const answer: AgentEvent = { type: "answer", text: "ok", charts: [] };
    const [turn] = run([
      asked,
      { type: "event", id: 1, event: answer },
      { type: "ended", id: 1 },
    ]).turns;
    expect(turn?.status).toBe("answered");
  });

  it("records a failed request and a stop", () => {
    const failed = run([asked, { type: "failed", id: 1, message: "Agent unavailable" }]).turns[0];
    expect(failed).toMatchObject({ status: "failed", error: "Agent unavailable" });
    const stopped = run([asked, { type: "stopped", id: 1 }]).turns[0];
    expect(stopped?.status).toBe("stopped");
  });

  it("ignores events for a question that is no longer running", () => {
    const state = run([
      asked,
      { type: "stopped", id: 1 },
      { type: "asked", id: 2, question: "Next?" },
      // A late "stopped" for question 1 must not stop question 2.
      { type: "stopped", id: 1 },
      { type: "event", id: 1, event: { type: "note", text: "late" } },
    ]);
    expect(state.turns.map((turn) => turn.status)).toEqual(["stopped", "running"]);
    expect(state.turns[0]?.steps).toEqual([]);
  });

  it("keeps at most MAX_TURNS questions", () => {
    const actions: ConversationAction[] = Array.from({ length: MAX_TURNS + 2 }, (_, i) => ({
      type: "asked",
      id: i + 1,
      question: `q${String(i + 1)}`,
    }));
    const state = run(actions);
    expect(state.turns).toHaveLength(MAX_TURNS);
    expect(state.turns[0]?.question).toBe("q3");
  });
});

describe("applyEvent", () => {
  const turn = run([asked]).turns[0];
  if (turn === undefined) {
    throw new Error("no turn");
  }

  it("keeps the charts made so far when the run fails without charts", () => {
    const withChart = applyEvent(turn, {
      type: "tool_result",
      id: "t9",
      name: "make_chart",
      isError: false,
      content: "",
      display: {},
      chart: CHART,
    });
    // The result had no matching call, so it becomes a step of its own.
    expect(withChart.steps).toHaveLength(1);
    const failed = applyEvent(withChart, { type: "error", message: "Stopped", charts: [] });
    expect(failed.charts).toEqual([CHART]);
    const replaced = applyEvent(withChart, { type: "error", message: "x", charts: [] });
    expect(replaced.error).toBe("x");
  });

  it("uses the error's charts when it has some", () => {
    const failed = applyEvent(turn, { type: "error", message: "x", charts: [CHART, CHART] });
    expect(failed.charts).toHaveLength(2);
  });

  it("keeps at most MAX_STEPS_PER_TURN steps", () => {
    let current = turn;
    for (let i = 0; i < MAX_STEPS_PER_TURN + 5; i += 1) {
      current = applyEvent(current, { type: "note", text: String(i) });
    }
    expect(current.steps).toHaveLength(MAX_STEPS_PER_TURN);
  });
});
