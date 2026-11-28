import styles from "./ResultTable.module.css";

/** The most rows shown on screen. The API sends at most 100 to the agent. */
export const MAX_TABLE_ROWS = 100;

const MIDNIGHT = /(?<=^\d{4}-\d{2}-\d{2})T00:00:00(\.0+)?$/;

/** A value as people read it: no long tails of decimals, no "T00:00:00" after a date. */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "number") {
    const digits =
      Math.abs(value) >= 1 ? { maximumFractionDigits: 2 } : { maximumSignificantDigits: 4 };
    return value.toLocaleString("en-US", { ...digits, useGrouping: false });
  }
  if (typeof value === "string") {
    // A date without a time of day: "2025-01-31T00:00:00.000" -> "2025-01-31".
    return value.replace(MIDNIGHT, "");
  }
  return JSON.stringify(value);
}

interface Props {
  columns: string[];
  rows: unknown[][];
  /** True when the query had more rows than `rows` holds. */
  truncated?: boolean;
}

/** A query result or sample rows, as a table that scrolls sideways when wide. */
export function ResultTable({ columns, rows, truncated = false }: Props) {
  const shown = rows.slice(0, MAX_TABLE_ROWS);
  const cut = truncated || shown.length < rows.length;
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th key={index} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className={typeof cell === "number" ? styles.number : undefined}
                >
                  {formatCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {cut && (
        <p className={styles.more}>
          Only the first {shown.length} rows are shown. The query returned more.
        </p>
      )}
    </div>
  );
}
