import { PlotlyChart } from "@/components/PlotlyChart";
import { ToolStepView } from "@/components/ToolStepView";
import type { Step, Turn } from "@/lib/conversation";
import { Markdown } from "@/lib/markdown";

import styles from "./ConversationView.module.css";

/** One question: the agent's steps, then its answer and charts. */
export function TurnView({ turn }: { turn: Turn }) {
  return (
    <li className={styles.turn}>
      <p className={styles.question}>{turn.question}</p>
      <StepList steps={turn.steps} running={turn.status === "running"} />
      <div aria-live="polite">
        <Outcome turn={turn} />
      </div>
      {turn.charts.map((chart, index) => (
        <PlotlyChart key={index} chart={chart} />
      ))}
    </li>
  );
}

/** While the agent works, its steps are open. Afterwards they fold away. */
function StepList({ steps, running }: { steps: Step[]; running: boolean }) {
  if (steps.length === 0) {
    return null;
  }
  const list = (
    <ol className={styles.steps}>
      {steps.map((step, index) => (
        <StepView key={index} step={step} />
      ))}
    </ol>
  );
  if (running) {
    return list;
  }
  const label = steps.length === 1 ? "Show the step" : `Show the ${String(steps.length)} steps`;
  return (
    <details className={styles.details}>
      <summary>{label} the agent took</summary>
      {list}
    </details>
  );
}

function StepView({ step }: { step: Step }) {
  if (step.kind === "tool") {
    return <ToolStepView step={step} />;
  }
  return (
    <li className={step.kind === "thinking" ? styles.thinking : styles.note}>
      {step.kind === "thinking" && <span className={styles.label}>Thinking</span>}
      <p>{step.text}</p>
    </li>
  );
}

function Outcome({ turn }: { turn: Turn }) {
  switch (turn.status) {
    case "running":
      return <p className={styles.working}>Working…</p>;
    case "answered":
      return (
        <div className={styles.answer}>
          <Markdown text={turn.answer} />
        </div>
      );
    case "failed":
      return <p className={styles.error}>{turn.error}</p>;
    case "stopped":
      return <p className={styles.muted}>Stopped. The agent did not finish this answer.</p>;
  }
}
