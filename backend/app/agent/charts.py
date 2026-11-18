"""Build Plotly charts as plain JSON ({data, layout}).

We build the JSON ourselves instead of using the plotly Python package: the
format is simple, and the frontend renders it with plotly.js.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Required, TypedDict

import pandas as pd

from app.datastore import records
from app.invariants import require

type ChartType = Literal["bar", "line", "scatter", "pie", "histogram"]

CHART_TYPES: Final = ("bar", "line", "scatter", "pie", "histogram")
MAX_SERIES: Final = 25  # more lines or bar groups than this is unreadable


class ChartError(ValueError):
    """The chart request does not fit the data. The message tells the model why."""


class Title(TypedDict):
    """A Plotly title."""

    text: str


class Axis(TypedDict):
    """A Plotly axis."""

    title: Title


class Trace(TypedDict, total=False):
    """One series of a Plotly chart."""

    type: Required[str]
    name: str
    mode: str
    x: list[object]
    y: list[object]
    labels: list[object]
    values: list[object]


class Layout(TypedDict, total=False):
    """Plotly layout: titles and axes."""

    title: Required[Title]
    xaxis: Axis
    yaxis: Axis
    barmode: str


class Chart(TypedDict):
    """A complete Plotly figure."""

    data: list[Trace]
    layout: Layout


@dataclass(frozen=True, slots=True)
class ChartRequest:
    """What the model asked to draw. `y` is empty for histograms, `color` may be empty."""

    chart_type: ChartType
    x: str
    y: str
    color: str
    title: str

    def __post_init__(self) -> None:
        if not self.x:
            raise ChartError("`x` must name a column of the query result.")
        if not self.y and self.chart_type != "histogram":
            raise ChartError(f"A {self.chart_type} chart needs `y`, the column with the values.")

    def needed_columns(self) -> list[str]:
        """The columns this chart reads from the query result."""
        y = "" if self.chart_type == "histogram" else self.y
        return [c for c in (self.x, y, self.color) if c]


def parse_chart_type(value: str) -> ChartType:
    """Check a chart type from the model.

    Raises:
        ChartError: If `value` is not a supported chart type.
    """
    match value:
        case "bar" | "line" | "scatter" | "pie" | "histogram":
            return value
        case _:
            raise ChartError(f"Unknown chart type {value!r}. Use one of: {', '.join(CHART_TYPES)}.")


def build_plotly_spec(df: pd.DataFrame, request: ChartRequest) -> Chart:
    """Turn a query result into a Plotly figure.

    Raises:
        ChartError: If the color column has more than MAX_SERIES values.
    """
    columns = [str(c) for c in df.columns]
    missing = [c for c in request.needed_columns() if c not in columns]
    require(not missing, f"columns must be checked before charting: {missing}")
    rows = records(_dates_as_text(df))
    color = columns.index(request.color) if request.color else None
    traces = [_trace(request, name, group, columns) for name, group in _split_series(rows, color)]
    return Chart(data=traces, layout=_layout(request))


def _dates_as_text(df: pd.DataFrame) -> pd.DataFrame:
    """Format dates as '2025-01-31', or with the time of day if any value has one."""
    frame = df.copy()
    for col in frame.columns:
        if not pd.api.types.is_datetime64_any_dtype(frame[col]):
            continue
        dates = frame[col].dropna()
        has_time = bool((dates != dates.dt.normalize()).any())
        frame[col] = frame[col].dt.strftime("%Y-%m-%dT%H:%M:%S" if has_time else "%Y-%m-%d")
    return frame


def _split_series(
    rows: list[list[object]], color: int | None
) -> list[tuple[str | None, list[list[object]]]]:
    """Group rows by the color column, in the order the values first appear."""
    if color is None:
        return [(None, rows)]
    groups: dict[str, list[list[object]]] = {}
    for row in rows:
        key = "(missing)" if row[color] is None else str(row[color])
        groups.setdefault(key, []).append(row)
    if len(groups) > MAX_SERIES:
        raise ChartError(
            f"The color column has {len(groups)} different values; a chart can show at most "
            f"{MAX_SERIES} series. Use a column with fewer values, or no color."
        )
    return list(groups.items())


def _trace(
    request: ChartRequest, name: str | None, rows: list[list[object]], columns: list[str]
) -> Trace:
    """Build one Plotly trace for one series."""
    trace = _shape(request, rows, columns)
    if name is not None:
        trace["name"] = name
    return trace


def _shape(request: ChartRequest, rows: list[list[object]], columns: list[str]) -> Trace:
    """The data part of a trace, in the shape its chart type needs."""
    x = _column(rows, columns, request.x)
    kind = request.chart_type
    match kind:
        case "histogram":
            return Trace(type="histogram", x=x)
        case "pie":
            return Trace(type="pie", labels=x, values=_column(rows, columns, request.y))
        case "bar":
            return Trace(type="bar", x=x, y=_column(rows, columns, request.y))
        case "line":
            y = _column(rows, columns, request.y)
            return Trace(type="scatter", mode="lines+markers", x=x, y=y)
        case "scatter":
            return Trace(type="scatter", mode="markers", x=x, y=_column(rows, columns, request.y))


def _column(rows: list[list[object]], columns: list[str], name: str) -> list[object]:
    """All values of one column."""
    require(name in columns, f"column {name!r} must be checked before charting")
    index = columns.index(name)
    return [row[index] for row in rows]


def _layout(request: ChartRequest) -> Layout:
    """Titles and axis labels for the chart."""
    layout = Layout(title=Title(text=request.title))
    if request.chart_type != "pie":
        layout["xaxis"] = Axis(title=Title(text=request.x))
        layout["yaxis"] = Axis(title=Title(text=request.y or "count"))
    if request.chart_type == "bar" and request.color:
        layout["barmode"] = "group"
    return layout
