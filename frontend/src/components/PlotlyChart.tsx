"use client";

import { useEffect, useRef, useState } from "react";

import type { Chart } from "@/lib/events";
import { isObject, type JsonObject } from "@/lib/json";

import styles from "./ConversationView.module.css";

/** Series colors that read well on light and dark backgrounds. */
export const COLORS = ["#4c78dd", "#e8833a", "#2fa38f", "#d05c8b", "#8f72d6", "#9a9a2e", "#3f9fd1"];

const CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["select2d", "lasso2d"],
};

/** The chart's title, for screen readers. */
export function chartTitle(chart: Chart): string {
  const { title } = chart.layout;
  return isObject(title) && typeof title.text === "string" && title.text !== ""
    ? title.text
    : "Chart";
}

/** The agent's layout, with colors that match the page (light or dark). */
export function themedLayout(layout: JsonObject, text: string, grid: string): JsonObject {
  const axis = (value: unknown) => ({
    ...(isObject(value) ? value : {}),
    gridcolor: grid,
    zerolinecolor: grid,
    automargin: true,
  });
  return {
    ...layout,
    xaxis: axis(layout.xaxis),
    yaxis: axis(layout.yaxis),
    font: { family: "inherit", color: text },
    colorway: COLORS,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    margin: { t: 56, r: 16, b: 48, l: 56 },
    autosize: true,
  };
}

async function draw(element: HTMLElement, chart: Chart): Promise<void> {
  // Plotly is large, so it is downloaded only when the first chart appears.
  const { default: Plotly } = await import("plotly.js-cartesian-dist-min");
  const style = getComputedStyle(element);
  const layout = themedLayout(
    chart.layout,
    style.getPropertyValue("--text").trim(),
    style.getPropertyValue("--border").trim(),
  );
  await Plotly.react(element, chart.data, layout, CONFIG);
}

async function erase(element: HTMLElement): Promise<void> {
  const { default: Plotly } = await import("plotly.js-cartesian-dist-min");
  Plotly.purge(element);
}

/** A chart from the agent, drawn by Plotly in the browser. */
export function PlotlyChart({ chart }: { chart: Chart }) {
  const box = useRef<HTMLElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const element = box.current;
    if (!element) {
      return;
    }
    let active = true;
    draw(element, chart).catch(() => {
      if (active) {
        setFailed(true);
      }
    });
    return () => {
      active = false;
      void erase(element);
    };
  }, [chart]);

  if (failed) {
    return <p className={styles.error}>The chart could not be drawn.</p>;
  }
  // A figure, not an image: Plotly adds buttons (zoom, download) inside it, and
  // an image can't contain anything a user can press.
  return <figure ref={box} className={styles.chart} aria-label={chartTitle(chart)} />;
}
