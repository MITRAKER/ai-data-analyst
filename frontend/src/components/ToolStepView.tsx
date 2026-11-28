import { ResultTable } from "@/components/ResultTable";
import type { ToolStep } from "@/lib/conversation";
import type { ToolResultEvent } from "@/lib/events";
import { isObject, isRows, isStringArray, type JsonObject } from "@/lib/json";

import styles from "./ConversationView.module.css";

// A Map, not an object: the name comes over the network, and an object would
// also "know" names such as "__proto__" or "constructor".
const LABELS = new Map([
  ["query_database", "SQL query"],
  ["run_python", "Python"],
  ["make_chart", "Chart"],
]);

/** The longest tool output shown on screen; the full text went to the agent. */
export const MAX_OUTPUT_CHARS = 4_000;

/** What the agent ran, and what came back. */
export function ToolStepView({ step }: { step: ToolStep }) {
  const { sql, code, purpose, title } = step.input;
  const caption = [purpose, title].find((text) => typeof text === "string" && text !== "");
  return (
    <li className={styles.tool}>
      <div className={styles.toolHead}>
        <span className={styles.badge}>{LABELS.get(step.name) ?? step.name}</span>
        {typeof caption === "string" && <span>{caption}</span>}
      </div>
      {typeof sql === "string" && (
        <pre className={styles.code}>
          <code>{sql}</code>
        </pre>
      )}
      {typeof code === "string" && (
        <pre className={styles.code}>
          <code>{code}</code>
        </pre>
      )}
      <ToolResult result={step.result} />
    </li>
  );
}

function clip(text: string): string {
  return text.length > MAX_OUTPUT_CHARS ? `${text.slice(0, MAX_OUTPUT_CHARS)}\n…` : text;
}

function ToolResult({ result }: { result: ToolResultEvent | null }) {
  if (result === null) {
    return <p className={styles.muted}>Running…</p>;
  }
  if (result.isError) {
    return <pre className={styles.toolError}>{clip(result.content)}</pre>;
  }
  if (result.chart) {
    return <p className={styles.muted}>The chart is shown with the answer.</p>;
  }
  const table = result.display.result;
  if (isQueryResult(table)) {
    return <ResultTable columns={table.columns} rows={table.rows} truncated={table.truncated} />;
  }
  const { stdout } = result.display;
  const output = typeof stdout === "string" ? stdout : result.content;
  return <pre className={styles.output}>{clip(output) || "(no output)"}</pre>;
}

interface QueryResult extends JsonObject {
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
}

/** The result of query_database: {columns, rows, row_count, truncated}. */
function isQueryResult(value: unknown): value is QueryResult {
  return (
    isObject(value) &&
    isStringArray(value.columns) &&
    isRows(value.rows) &&
    typeof value.truncated === "boolean"
  );
}
