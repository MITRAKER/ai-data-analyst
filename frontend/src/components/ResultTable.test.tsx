import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatCell, MAX_TABLE_ROWS, ResultTable } from "@/components/ResultTable";

describe("formatCell", () => {
  it.each([
    [1234567.891, "1234567.89"],
    [42, "42"],
    [0.000123456, "0.0001235"],
    [-3.14159, "-3.14"],
    ["2025-01-31T00:00:00.000", "2025-01-31"],
    ["2025-01-31T09:30:00", "2025-01-31T09:30:00"],
    ["West", "West"],
    [null, ""],
    [undefined, ""],
    [true, "true"],
    [{ a: 1 }, '{"a":1}'],
  ])("shows %j as %j", (value, shown) => {
    expect(formatCell(value)).toBe(shown);
  });
});

describe("ResultTable", () => {
  it("shows the columns and rows, numbers aligned right", () => {
    render(<ResultTable columns={["region", "revenue"]} rows={[["West", 5.5]]} />);
    expect(screen.getByRole("columnheader", { name: "revenue" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "5.5" }).className).toMatch(/number/);
    expect(screen.queryByText(/Only the first/)).toBeNull();
  });

  it("says when the query returned more rows than it shows", () => {
    render(<ResultTable columns={["n"]} rows={[[1]]} truncated />);
    expect(
      screen.getByText("Only the first 1 rows are shown. The query returned more."),
    ).toBeVisible();
  });

  it("shows at most MAX_TABLE_ROWS rows", () => {
    const rows = Array.from({ length: MAX_TABLE_ROWS + 5 }, (_, i) => [i]);
    render(<ResultTable columns={["n"]} rows={rows} />);
    expect(screen.getAllByRole("row")).toHaveLength(MAX_TABLE_ROWS + 1); // plus the header
    expect(screen.getByText(/Only the first 100 rows/)).toBeVisible();
  });
});
