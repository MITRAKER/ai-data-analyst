"use client";

import type { ChangeEvent } from "react";

import { ResultTable } from "@/components/ResultTable";
import type { Datasets } from "@/hooks/useDatasets";
import type { DatasetInfo } from "@/lib/api";

import styles from "./DatasetPanel.module.css";

/** The uploaded datasets, an upload button, and details of the chosen dataset. */
export function DatasetPanel({ datasets }: { datasets: Datasets }) {
  const { names, selected, error, busy, upload, select } = datasets;

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // so that choosing the same file again works too
    if (file) {
      upload(file);
    }
  }

  return (
    <aside className={styles.panel} aria-label="Datasets">
      <div className={styles.head}>
        <h2 className={styles.heading}>Datasets</h2>
        <label className={styles.upload} aria-disabled={busy}>
          {busy ? "Working…" : "Upload CSV"}
          <input
            type="file"
            accept=".csv,text/csv"
            className="visually-hidden"
            disabled={busy}
            onChange={onFile}
          />
        </label>
      </div>
      {error !== "" && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {names.length === 0 ? (
        <p className={styles.muted}>No datasets yet.</p>
      ) : (
        <ul className={styles.list}>
          {names.map((name) => (
            <li key={name}>
              <button
                type="button"
                className={styles.item}
                aria-pressed={selected?.name === name}
                onClick={() => {
                  select(name);
                }}
              >
                {name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected && <DatasetDetails info={selected} />}
    </aside>
  );
}

function DatasetDetails({ info }: { info: DatasetInfo }) {
  return (
    <section className={styles.details} aria-label={`Details of ${info.name}`}>
      <h3 className={styles.name}>{info.name}</h3>
      <p className={styles.muted}>
        {info.rowCount.toLocaleString("en-US")} rows, {info.columns.length} columns
      </p>
      <ul className={styles.columns}>
        {info.columns.map((column) => (
          <li key={column.name}>
            <span>{column.name}</span>
            <span className={styles.type}>{column.type}</span>
          </li>
        ))}
      </ul>
      <h4 className={styles.subheading}>First rows</h4>
      <ResultTable columns={info.columns.map((column) => column.name)} rows={info.sample} />
    </section>
  );
}
