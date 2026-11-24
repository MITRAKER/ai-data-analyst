"use client";

import type { ChangeEvent } from "react";

import { ResultTable } from "@/components/ResultTable";
import type { Datasets } from "@/hooks/useDatasets";
import type { DatasetInfo } from "@/lib/api";

import styles from "./DatasetPanel.module.css";

/** The uploaded datasets, an upload button, and details of the chosen dataset. */
export function DatasetPanel({ datasets }: { datasets: Datasets }) {
  const { selected, error, uploading, upload } = datasets;

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
        <label className={styles.upload} aria-disabled={uploading}>
          {uploading ? "Uploading…" : "Upload CSV"}
          <input
            type="file"
            accept=".csv,text/csv"
            className="visually-hidden"
            disabled={uploading}
            onChange={onFile}
          />
        </label>
      </div>
      {error !== "" && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <NameList datasets={datasets} />
      {selected && <DatasetDetails info={selected} />}
    </aside>
  );
}

/** A button for each dataset, or why there are none to show. */
function NameList({ datasets }: { datasets: Datasets }) {
  const { names, selected, error, select } = datasets;
  if (names === null) {
    // Still loading. (If loading failed, the error above says so.)
    return error === "" ? <p className={styles.muted}>Loading datasets…</p> : null;
  }
  if (names.length === 0) {
    return <p className={styles.muted}>No datasets yet.</p>;
  }
  return (
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
