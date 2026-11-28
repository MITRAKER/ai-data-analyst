/**
 * The state of the conversation, and how each event changes it.
 *
 * `conversationReducer` is a pure function: (state, action) -> new state. It
 * never changes the old state, it never calls the network, and the same input
 * always gives the same output. React's useReducer calls it for every action,
 * and the tests call it directly, without a browser.
 */

import type { AgentEvent, Chart, ToolResultEvent } from "@/lib/events";
import type { JsonObject } from "@/lib/json";

/** The most questions kept on screen. Older ones are dropped. */
export const MAX_TURNS = 50;

/** The most steps kept for one question. The agent stops long before this. */
export const MAX_STEPS_PER_TURN = 500;

/**
 * The most charts kept for one question. The agent can make at most 96 (12
 * steps of up to 8 tool calls), so this only stops a broken server.
 */
export const MAX_CHARTS_PER_TURN = 100;

/** A tool the agent ran: what it asked for, and (once it arrives) the result. */
export interface ToolStep {
  kind: "tool";
  id: string;
  name: string;
  input: JsonObject;
  result: ToolResultEvent | null;
}

/** Something the agent thought or said between tool calls. */
export interface TextStep {
  kind: "thinking" | "note";
  text: string;
}

export type Step = ToolStep | TextStep;

export type TurnStatus = "running" | "answered" | "failed" | "stopped";

/** One question and everything the agent did to answer it. */
export interface Turn {
  id: number;
  question: string;
  steps: Step[];
  charts: Chart[];
  answer: string;
  error: string;
  status: TurnStatus;
}

export interface Conversation {
  turns: Turn[];
}

/**
 * What can happen to a question. Each action names its question by `id`, so a
 * late event from a question the user stopped can't change a newer one.
 */
export type ConversationAction =
  | { type: "asked"; id: number; question: string }
  | { type: "event"; id: number; event: AgentEvent }
  | { type: "ended"; id: number }
  | { type: "failed"; id: number; message: string }
  | { type: "stopped"; id: number };

export const emptyConversation: Conversation = { turns: [] };

export const ENDED_EARLY = "The connection closed before the agent finished. Please try again.";

function withStep(turn: Turn, step: Step): Turn {
  return turn.steps.length < MAX_STEPS_PER_TURN ? { ...turn, steps: [...turn.steps, step] } : turn;
}

/** At most MAX_CHARTS_PER_TURN charts. */
function capped(charts: Chart[]): Chart[] {
  return charts.slice(0, MAX_CHARTS_PER_TURN);
}

/** Attach a tool result to the call it answers. */
function withResult(turn: Turn, result: ToolResultEvent): Turn {
  const charts = result.chart ? capped([...turn.charts, result.chart]) : turn.charts;
  const index = turn.steps.findLastIndex((step) => step.kind === "tool" && step.id === result.id);
  if (index === -1) {
    const orphan: ToolStep = { kind: "tool", id: result.id, name: result.name, input: {}, result };
    return { ...withStep(turn, orphan), charts };
  }
  const steps = turn.steps.map((step, i) => (i === index ? { ...step, result } : step));
  return { ...turn, steps, charts };
}

/** How one event from the agent changes the question it belongs to. */
export function applyEvent(turn: Turn, event: AgentEvent): Turn {
  switch (event.type) {
    case "thinking":
    case "note":
      return withStep(turn, { kind: event.type, text: event.text });
    case "tool_call":
      return withStep(turn, {
        kind: "tool",
        id: event.id,
        name: event.name,
        input: event.input,
        result: null,
      });
    case "tool_result":
      return withResult(turn, event);
    case "answer":
      return { ...turn, status: "answered", answer: event.text, charts: capped(event.charts) };
    case "error": {
      const charts = event.charts.length > 0 ? capped(event.charts) : turn.charts;
      return { ...turn, status: "failed", error: event.message, charts };
    }
  }
}

function newTurn(id: number, question: string): Turn {
  return { id, question, steps: [], charts: [], answer: "", error: "", status: "running" };
}

/** Apply `change` to question `id`, but only while that question is still running. */
function updateRunning(
  state: Conversation,
  id: number,
  change: (turn: Turn) => Turn,
): Conversation {
  const turn = state.turns.find((candidate) => candidate.id === id);
  if (turn?.status !== "running") {
    return state; // for example, an event that arrived after the user pressed Stop
  }
  return { turns: state.turns.map((candidate) => (candidate === turn ? change(turn) : candidate)) };
}

export function conversationReducer(state: Conversation, action: ConversationAction): Conversation {
  switch (action.type) {
    case "asked":
      return { turns: [...state.turns, newTurn(action.id, action.question)].slice(-MAX_TURNS) };
    case "event":
      return updateRunning(state, action.id, (turn) => applyEvent(turn, action.event));
    case "ended":
      return updateRunning(state, action.id, (turn) => ({
        ...turn,
        status: "failed",
        error: ENDED_EARLY,
      }));
    case "failed":
      return updateRunning(state, action.id, (turn) => ({
        ...turn,
        status: "failed",
        error: action.message,
      }));
    case "stopped":
      return updateRunning(state, action.id, (turn) => ({ ...turn, status: "stopped" }));
  }
}
