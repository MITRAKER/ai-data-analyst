"use client";

import { useEffect, useState } from "react";

import { getDataset, listDatasets, uploadDataset, type DatasetInfo } from "@/lib/api";
import { messageOf } from "@/lib/errors";

export interface Datasets {
  names: string[];
  selected: DatasetInfo | null;
  error: string;
  busy: boolean;
  upload: (file: File) => void;
  select: (name: string) => void;
}

/** The uploaded datasets, the one the user is looking at, and how to add one. */
export function useDatasets(): Datasets {
  const [names, setNames] = useState<string[]>([]);
  const [selected, setSelected] = useState<DatasetInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true; // false once the component is gone
    listDatasets().then(
      (found) => {
        if (active) {
          setNames(found);
        }
      },
      (reason: unknown) => {
        if (active) {
          setError(messageOf(reason));
        }
      },
    );
    return () => {
      active = false;
    };
  }, []);

  async function run(task: () => Promise<DatasetInfo>, refresh: boolean): Promise<void> {
    setBusy(true);
    setError("");
    try {
      const info = await task();
      setSelected(info);
      if (refresh) {
        setNames(await listDatasets());
      }
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setBusy(false);
    }
  }

  return {
    names,
    selected,
    error,
    busy,
    upload: (file) => void run(() => uploadDataset(file), true),
    select: (name) => void run(() => getDataset(name), false),
  };
}
