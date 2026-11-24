"use client";

import { useEffect, useRef, useState } from "react";

import { isChart, type Chart } from "@/lib/events";
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

/**
 * A copy of the chart in which no text can become a link or styled text.
 *
 * Plotly reads a few HTML tags in every text it draws: `<a href=...>` becomes
 * a link that can be clicked, and `<span style=...>` can set any CSS. A
 * chart's text comes from the agent and from the cells of a CSV file, so a
 * crafted file could put a fake "sign in again" link on the page. So every
 * "&", "<" and ">" in every string is escaped. Plotly turns "&lt;" back into
 * "<" when it draws the text, so the chart still reads the same.
 */
export function escapeChartText(chart: Chart): Chart {
  const escape = (_key: string, value: unknown): unknown =>
    typeof value === "string"
      ? value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      : value;
  const copy: unknown = JSON.parse(JSON.stringify(chart, escape));
  if (!isChart(copy)) {
    throw new TypeError("The chart could not be copied.");
  }
  return copy;
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
  const safe = escapeChartText(chart);
  const layout = themedLayout(
    safe.layout,
    style.getPropertyValue("--text").trim(),
    style.getPropertyValue("--border").trim(),
  );
  await Plotly.react(element, safe.data, layout, CONFIG);
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
