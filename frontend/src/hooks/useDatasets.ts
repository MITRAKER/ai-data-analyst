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
 * Ask for the names of all datasets, and show them, unless a newer request
 * was made meanwhile. An older request that fails late is ignored too: the
 * newer one decides.
 */
async function refreshNames(
  lists: RefObject<number>,
  setNames: (names: string[]) => void,
): Promise<void> {
  const isNewest = newRequest(lists);
  try {
    const found = await listDatasets();
    if (isNewest()) {
      setNames(found);
    }
  } catch (reason) {
    if (isNewest()) {
      throw reason;
    }
  }
}

/**
 * The uploaded datasets, the one the user is looking at, and how to add one.
 *
 * The user can click a dataset, or upload a file, before the server has
 * answered the last click. The newest choice wins:
 * - a click shows its dataset, or its error, only if no dataset was opened
 *   after it;
 * - an upload opens its dataset, unless the user clicked another one
 *   meanwhile. (A dataset with the same name was just replaced, so the
 *   upload's new version wins over a click on it.) An upload's own error
 *   always shows: the file wasn't added, whatever else happened meanwhile.
 *   So does an error in reloading the list after it.
 */
export function useDatasets(): Datasets {
  const [names, setNames] = useState<string[] | null>(null);
  const [selected, setSelected] = useState<DatasetInfo | null>(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const lists = useRef(0); // the requests for the list of names
  const opens = useRef(0); // the clicks on a dataset, and the uploads that opened one
  const clicked = useRef(""); // the name of the dataset clicked last

  useEffect(() => {
    refreshNames(lists, setNames).catch((reason: unknown) => {
      setError(messageOf(reason));
    });
  }, []);

  async function select(name: string): Promise<void> {
    const isNewest = newRequest(opens);
    clicked.current = name;
    setError("");
    try {
      const info = await getDataset(name);
      if (isNewest()) {
        setSelected(info);
      }
    } catch (reason) {
      if (isNewest()) {
        setError(messageOf(reason));
      }
    }
  }

  async function upload(file: File): Promise<void> {
    const opensBefore = opens.current;
    setUploading(true);
    setError("");
    try {
      const info = await uploadDataset(file);
      // Open it, unless the user clicked another dataset meanwhile.
      if (opens.current === opensBefore || clicked.current === info.name) {
        newRequest(opens); // so that answers to older clicks are ignored
        setSelected(info);
        setError(""); // an older click's error doesn't belong next to it
      }
      await refreshNames(lists, setNames);
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
    select: (name) => void select(name),
  };
}
