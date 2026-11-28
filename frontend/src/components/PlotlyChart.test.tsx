import { render, screen } from "@testing-library/react";
import Plotly from "plotly.js-cartesian-dist-min";
import { describe, expect, it, vi } from "vitest";

import {
  chartTitle,
  COLORS,
  escapeChartText,
  PlotlyChart,
  themedLayout,
} from "@/components/PlotlyChart";
import type { Chart } from "@/lib/events";
import { CHART } from "@/test/fakes";

vi.mock("plotly.js-cartesian-dist-min", () => ({
  default: { react: vi.fn(() => Promise.resolve()), purge: vi.fn() },
}));

describe("PlotlyChart", () => {
  it("draws the chart with Plotly, and removes it when it goes away", async () => {
    const { unmount } = render(<PlotlyChart chart={CHART} />);
    const box = screen.getByRole("figure", { name: "Revenue by region" });
    await vi.waitFor(() => {
      expect(Plotly.react).toHaveBeenCalledWith(
        box,
        CHART.data,
        expect.objectContaining({ title: CHART.layout.title, colorway: COLORS }),
        expect.objectContaining({ displaylogo: false }),
      );
    });
    unmount();
    await vi.waitFor(() => {
      expect(Plotly.purge).toHaveBeenCalledWith(box);
    });
  });

  it("says so when the chart can't be drawn", async () => {
    vi.mocked(Plotly.react).mockRejectedValueOnce(new Error("bad figure"));
    render(<PlotlyChart chart={CHART} />);
    expect(await screen.findByText("The chart could not be drawn.")).toBeInTheDocument();
  });
});

/** A chart whose text, from a crafted CSV file, tries to add a link and styles. */
const CRAFTED: Chart = {
  data: [
    {
      type: "bar",
      x: ['<a href="https://evil.example">Sign in again</a>', "R&D"],
      y: [1, 2],
      hovertemplate: '<span style="position:fixed">%{x}</span>',
    },
  ],
  layout: { title: { text: "<b>Revenue</b> by team" } },
};

describe("escapeChartText", () => {
  it("escapes the characters Plotly reads as HTML, in every string", () => {
    const safe = escapeChartText(CRAFTED);
    expect(safe.data[0]).toEqual({
      type: "bar",
      x: ['&lt;a href="https://evil.example"&gt;Sign in again&lt;/a&gt;', "R&amp;D"],
      y: [1, 2],
      hovertemplate: '&lt;span style="position:fixed"&gt;%{x}&lt;/span&gt;',
    });
    expect(safe.layout).toEqual({ title: { text: "&lt;b&gt;Revenue&lt;/b&gt; by team" } });
    // The chart from the agent stays as it was.
    expect(CRAFTED.layout).toEqual({ title: { text: "<b>Revenue</b> by team" } });
  });

  it("refuses something that doesn't copy into a chart", () => {
    const odd: Chart = { data: [], layout: {} };
    Object.defineProperty(odd, "toJSON", { value: () => null });
    expect(() => escapeChartText(odd)).toThrow(TypeError);
  });

  it("is what Plotly draws", async () => {
    render(<PlotlyChart chart={CRAFTED} />);
    await vi.waitFor(() => {
      expect(Plotly.react).toHaveBeenCalledWith(
        expect.anything(),
        escapeChartText(CRAFTED).data,
        expect.objectContaining({ title: { text: "&lt;b&gt;Revenue&lt;/b&gt; by team" } }),
        expect.anything(),
      );
    });
  });
});

describe("themedLayout", () => {
  it("keeps the agent's layout and adds the page's colors", () => {
    const layout = themedLayout(CHART.layout, "#111", "#ccc");
    expect(layout.title).toEqual(CHART.layout.title);
    expect(layout.xaxis).toEqual({
      title: { text: "region" },
      gridcolor: "#ccc",
      zerolinecolor: "#ccc",
      automargin: true,
    });
    // An axis the agent didn't set gets the colors too.
    expect(layout.yaxis).toMatchObject({ gridcolor: "#ccc" });
    expect(layout.font).toEqual({ family: "inherit", color: "#111" });
  });
});

describe("chartTitle", () => {
  it("uses the title, or a plain label without one", () => {
    expect(chartTitle(CHART)).toBe("Revenue by region");
    expect(chartTitle({ data: [], layout: { title: { text: "" } } })).toBe("Chart");
    expect(chartTitle({ data: [], layout: {} })).toBe("Chart");
  });
});
