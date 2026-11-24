import type { AgentState } from "@/hooks/useAgentStatus";

import styles from "./ConversationView.module.css";

/** A warning when the agent can't answer questions, with the reason. */
export function StatusBanner({ agent }: { agent: AgentState }) {
  if (agent.kind === "checking" || agent.kind === "ready") {
    return null;
  }
  const title =
    agent.kind === "unavailable"
      ? "The agent can't answer questions yet."
      : "The analysis server can't be reached.";
  return (
    <div className={styles.banner} role="status">
      <strong>{title}</strong> {agent.detail}
    </div>
  );
}
