"use client";

import { useReducer, useRef } from "react";

import { askQuestion } from "@/lib/api";
import { conversationReducer, emptyConversation, type Turn } from "@/lib/conversation";
import { messageOf } from "@/lib/errors";

export interface ConversationControls {
  turns: Turn[];
  busy: boolean;
  ask: (question: string) => void;
  stop: () => void;
}

/** The questions so far, and how to ask a new one or stop the running one. */
export function useConversation(): ConversationControls {
  const [state, dispatch] = useReducer(conversationReducer, emptyConversation);
  const nextId = useRef(1);
  const running = useRef<AbortController | null>(null);

  async function stream(id: number, question: string, controller: AbortController) {
    try {
      for await (const event of askQuestion(question, controller.signal)) {
        dispatch({ type: "event", id, event });
      }
      // Does nothing if an answer or an error already ended the question.
      dispatch({ type: "ended", id });
    } catch (error) {
      const stopped = controller.signal.aborted;
      dispatch(
        stopped ? { type: "stopped", id } : { type: "failed", id, message: messageOf(error) },
      );
    } finally {
      if (running.current === controller) {
        running.current = null;
      }
    }
  }

  function ask(question: string): void {
    running.current?.abort(); // only one question at a time
    const controller = new AbortController();
    running.current = controller;
    const id = nextId.current;
    nextId.current += 1;
    dispatch({ type: "asked", id, question });
    void stream(id, question, controller);
  }

  function stop(): void {
    running.current?.abort();
  }

  const busy = state.turns.at(-1)?.status === "running";
  return { turns: state.turns, busy, ask, stop };
}
