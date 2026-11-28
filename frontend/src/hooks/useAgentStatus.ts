"use client";

import { useEffect, useState } from "react";

import { getAgentStatus } from "@/lib/api";
import { messageOf } from "@/lib/errors";

export type AgentState =
  | { kind: "checking" }
  | { kind: "ready" }
  | { kind: "unavailable"; detail: string }
  | { kind: "unreachable"; detail: string };

/** Asks the server once whether the agent can answer questions. */
export function useAgentStatus(): AgentState {
  const [state, setState] = useState<AgentState>({ kind: "checking" });
  useEffect(() => {
    let active = true;
    getAgentStatus().then(
      (status) => {
        if (active) {
          setState(
            status.ready ? { kind: "ready" } : { kind: "unavailable", detail: status.detail },
          );
        }
      },
      (reason: unknown) => {
        if (active) {
          setState({ kind: "unreachable", detail: messageOf(reason) });
        }
      },
    );
    return () => {
      active = false;
    };
  }, []);
  return state;
}
