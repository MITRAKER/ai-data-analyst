"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

import { getDataset, listDatasets, uploadDataset, type DatasetInfo } from "@/lib/api";
import { messageOf } from "@/lib/errors";

export interface Datasets {
  /** The datasets' names, or null until the server has sent them. */
  names: string[] | null;
  selected: DatasetInfo | null;
  error: string;
  /** True while a file is uploading. */
  uploading: boolean;
  upload: (file: File) => void;
  select: (name: string) => void;
}

/**
 * Number a new request. The function it returns says whether the request is
 * still the newest one, so that a slow answer to an older request can't
 * replace the answer to a newer one.
 */
function newRequest(counter: RefObject<number>): () => boolean {
  counter.current += 1;
  const ticket = counter.current;
  return () => ticket === counter.current;
}

/**
 * The names of all datasets, or null if a newer request was made meanwhile.
 * An older request that fails late is ignored too: the newer one decides.
 */
async function newestNames(lists: RefObject<number>): Promise<string[] | null> {
  const isNewest = newRequest(lists);
  try {
    const found = await listDatasets();
    return isNewest() ? found : null;
  } catch (reason) {
    if (isNewest()) {
      throw reason;
    }
    return null;
  }
}

/** The uploaded datasets, the one the user is looking at, and how to add one. */
export function useDatasets(): Datasets {
  const [names, setNames] = useState<string[] | null>(null);
  const [selected, setSelected] = useState<DatasetInfo | null>(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const lists = useRef(0); // the requests for the list of names
  const shows = useRef(0); // the uploads, and the clicks on a dataset

  useEffect(() => {
    newestNames(lists).then(
      (found) => {
        if (found) {
          setNames(found);
        }
      },
      (reason: unknown) => {
        setError(messageOf(reason));
      },
    );
  }, []);

  /** Run `task`, and show the dataset it returns. Returns false if it failed. */
  async function show(task: () => Promise<DatasetInfo>): Promise<boolean> {
    const isNewest = newRequest(shows);
    setError("");
    try {
      const info = await task();
      if (isNewest()) {
        setSelected(info);
      }
      return true;
    } catch (reason) {
      setError(messageOf(reason));
      return false;
    }
  }

  async function upload(file: File): Promise<void> {
    setUploading(true);
    try {
      const found = (await show(() => uploadDataset(file))) ? await newestNames(lists) : null;
      if (found) {
        setNames(found);
      }
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setUploading(false);
    }
  }

  return {
    names,
    selected,
    error,
    uploading,
    upload: (file) => void upload(file),
    select: (name) => void show(() => getDataset(name)),
  };
}
