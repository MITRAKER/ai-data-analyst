"""The agent's tools: what Claude is allowed to *do*.

Each tool has two halves:
1. A **definition** sent to Claude: a name, a description, and a JSON Schema for
   the inputs. Claude never runs anything itself. It replies with
   "please call query_database with {sql: ...}".
2. An **implementation** here in Python that actually does the work and returns
   a result, which we send back to Claude.

The descriptions matter a lot: they are effectively part of the prompt. Good
descriptions say what the tool is for, when to use it, and what comes back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..datastore import DataStore
from ..sql_guard import UnsafeSQLError
from .sandbox import SandboxError, run_python

MAX_SQL_ROWS_FOR_AGENT = 100  # what Claude sees from query_database
MAX_ROWS_FOR_CODE = 200_000  # what run_python / make_chart can load
MAX_CHART_POINTS = 5_000

CHART_TYPES = ["bar", "line", "scatter", "pie", "histogram"]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "query_database",
        "description": (
            "Run ONE read-only DuckDB SQL SELECT query against the uploaded datasets and get "
            f"the rows back (at most {MAX_SQL_ROWS_FOR_AGENT}). Use this for filtering, "
            "grouping, aggregating and joining. Prefer aggregating in SQL over pulling raw rows. "
            "If the query fails you get the database error message: fix the query and try again."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single DuckDB SELECT statement."},
                "purpose": {
                    "type": "string",
                    "description": "One short sentence for the user: why you are running this query.",
                },
            },
            "required": ["sql", "purpose"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_python",
        "description": (
            "Run Python (pandas/numpy, plus scipy if installed) for analysis that is awkward in SQL: "
            "statistics, correlations, growth rates, outlier detection, forecasting. First the "
            "`sql` query runs and its result is loaded as a pandas DataFrame named `df` "
            f"(up to {MAX_ROWS_FOR_CODE:,} rows). `pd` and `np` are already imported. Only what "
            "you print() is returned, so print concise results. No file, network or OS access."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query whose result becomes `df`."},
                "code": {"type": "string", "description": "Python code that uses `df` and prints results."},
                "purpose": {"type": "string", "description": "One short sentence for the user."},
            },
            "required": ["sql", "code", "purpose"],
            "additionalProperties": False,
        },
    },
    {
        "name": "make_chart",
        "description": (
            "Create a chart to show the user. The `sql` query should return exactly the data to "
            "plot, already aggregated (e.g. one row per month). `x` and `y` are column names from "
            "that result. Use `color` to split into one series per value of a column (or empty "
            "string for none). Pick the chart type that fits: line for trends over time, bar for "
            "comparing categories, scatter for relationships, histogram for distributions, pie "
            "only for a few parts of a whole. The chart is shown to the user automatically."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "chart_type": {"type": "string", "enum": CHART_TYPES},
                "x": {"type": "string", "description": "Column for the x axis (or pie labels)."},
                "y": {"type": "string", "description": "Column for the y axis (or pie values). Empty for histogram."},
                "color": {"type": "string", "description": "Optional column to split series by, or empty string."},
                "title": {"type": "string"},
            },
            "required": ["sql", "chart_type", "x", "y", "color", "title"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class ToolOutcome:
    """What a tool returns. `content` goes back to Claude; `chart` goes to the user."""

    content: str
    is_error: bool = False
    chart: dict[str, Any] | None = None
    display: dict[str, Any] = field(default_factory=dict)  # extra info for the UI


class ToolExecutor:
    def __init__(self, store: DataStore) -> None:
        self.store = store

    def execute(self, name: str, tool_input: dict[str, Any]) -> ToolOutcome:
        handler = {
            "query_database": self._query_database,
            "run_python": self._run_python,
            "make_chart": self._make_chart,
        }.get(name)
        if handler is None:
            return ToolOutcome(f"Unknown tool: {name}", is_error=True)
        try:
            return handler(**tool_input)
        except (UnsafeSQLError, SandboxError) as exc:
            # Expected failures: send the message back so Claude can correct itself.
            return ToolOutcome(str(exc), is_error=True)
        except TypeError as exc:
            return ToolOutcome(f"Invalid tool input: {exc}", is_error=True)

    # ---------- tool implementations ----------

    def _query_database(self, sql: str, purpose: str = "") -> ToolOutcome:
        result = self.store.run_query(sql, max_rows=MAX_SQL_ROWS_FOR_AGENT)
        payload = result.to_dict()
        if result.truncated:
            payload["note"] = (
                f"Only the first {MAX_SQL_ROWS_FOR_AGENT} rows are shown. "
                "Aggregate in SQL if you need the whole picture."
            )
        return ToolOutcome(json.dumps(payload, default=str), display={"result": payload})

    def _run_python(self, sql: str, code: str, purpose: str = "") -> ToolOutcome:
        df, truncated = self.store.query_df(sql, max_rows=MAX_ROWS_FOR_CODE)
        result = run_python(code, df)
        text = result.stdout if result.ok else f"{result.stdout}\nERROR:\n{result.error}".strip()
        if truncated:
            text += f"\n(note: df was limited to the first {MAX_ROWS_FOR_CODE:,} rows)"
        return ToolOutcome(text, is_error=not result.ok, display=result.to_dict())

    def _make_chart(self, sql: str, chart_type: str, x: str, y: str, color: str, title: str) -> ToolOutcome:
        df, truncated = self.store.query_df(sql, max_rows=MAX_CHART_POINTS)
        needed = [c for c in (x, y if chart_type != "histogram" else "", color) if c]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            return ToolOutcome(
                f"Column(s) {missing} not in query result. Available: {list(df.columns)}",
                is_error=True,
            )
        chart = build_plotly_spec(df, chart_type, x, y, color, title)
        note = " (data truncated to the first 5,000 rows)" if truncated else ""
        return ToolOutcome(
            f"Chart '{title}' created with {len(df)} rows{note} and shown to the user.",
            chart=chart,
        )


def build_plotly_spec(
    df: pd.DataFrame, chart_type: str, x: str, y: str, color: str, title: str
) -> dict[str, Any]:
    """Build a Plotly figure as plain JSON ({data, layout}).

    We build the JSON ourselves instead of using the plotly Python package: the
    format is simple, and the frontend renders it with plotly.js.
    """
    df = df.copy()
    for col in df.columns:  # dates -> ISO strings so the JSON is clean
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")

    def values(frame: pd.DataFrame, col: str) -> list:
        return json.loads(frame[col].to_json(orient="values"))

    groups = [(None, df)] if not color else [(str(k), g) for k, g in df.groupby(color, sort=True)]
    traces: list[dict[str, Any]] = []
    for name, frame in groups:
        if chart_type == "pie":
            trace = {"type": "pie", "labels": values(frame, x), "values": values(frame, y)}
        elif chart_type == "histogram":
            trace = {"type": "histogram", "x": values(frame, x)}
        else:
            trace = {"type": "bar" if chart_type == "bar" else "scatter", "x": values(frame, x), "y": values(frame, y)}
            if chart_type == "line":
                trace["mode"] = "lines+markers"
            elif chart_type == "scatter":
                trace["mode"] = "markers"
        if name is not None:
            trace["name"] = name
        traces.append(trace)

    layout: dict[str, Any] = {"title": {"text": title}}
    if chart_type != "pie":
        layout["xaxis"] = {"title": {"text": x}}
        layout["yaxis"] = {"title": {"text": y or "count"}}
    if chart_type == "bar" and color:
        layout["barmode"] = "group"
    return {"data": traces, "layout": layout}
