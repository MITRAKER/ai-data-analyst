"""The agent's tools: what Claude is allowed to *do*.

Each tool has two halves:
1. A **definition** sent to Claude: a name, a description, and a JSON Schema for
   the inputs. Claude never runs anything itself. It replies with
   "please call query_database with {sql: ...}".
2. An **implementation** here in Python that checks the input, does the work
   and returns a result, which we send back to Claude.

The descriptions matter a lot: they are effectively part of the prompt. Good
descriptions say what the tool is for, when to use it, and what comes back.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Final

import pandas as pd
from anthropic.types.beta import BetaToolParam

from app.agent.charts import (
    CHART_TYPES,
    Chart,
    ChartError,
    ChartRequest,
    build_plotly_spec,
    parse_chart_type,
)
from app.agent.sandbox import DEFAULT_LIMITS, SandboxError, SandboxLimits, run_python
from app.datastore import DataStore
from app.invariants import require
from app.sql_guard import UnsafeSQLError

MAX_SQL_ROWS_FOR_AGENT: Final = 100  # what Claude sees from query_database
MAX_ROWS_FOR_CODE: Final = 200_000  # what run_python can load into `df`
MAX_CHART_POINTS: Final = 5_000
MAX_INPUT_CHARS: Final = 20_000  # the longest text any tool input may be
MAX_RESULT_CHARS: Final = 50_000  # the longest tool result sent back to Claude

logger = logging.getLogger(__name__)


class ToolInputError(ValueError):
    """The model sent a tool input with the wrong shape. The message says what to fix."""


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """What a tool returns. `content` goes back to Claude; `chart` goes to the user."""

    content: str
    is_error: bool = False
    chart: Chart | None = None
    display: dict[str, object] = field(default_factory=dict)  # extra info for the UI


def tool_definitions() -> list[BetaToolParam]:
    """The tools Claude may call, in the format the Messages API expects."""
    return [_query_database_tool(), _run_python_tool(), _make_chart_tool()]


def _query_database_tool() -> BetaToolParam:
    return {
        "name": "query_database",
        "description": (
            "Run ONE read-only DuckDB SQL SELECT query against the uploaded datasets and get "
            f"the rows back (at most {MAX_SQL_ROWS_FOR_AGENT}). Use this for filtering, "
            "grouping, aggregating and joining. Prefer aggregating in SQL over pulling raw "
            "rows. If the query fails you get the database error message: fix the query and "
            "try again."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single DuckDB SELECT statement."},
                "purpose": {
                    "type": "string",
                    "description": "One short sentence for the user: why you run this query.",
                },
            },
            "required": ["sql", "purpose"],
            "additionalProperties": False,
        },
    }


def _run_python_tool() -> BetaToolParam:
    return {
        "name": "run_python",
        "description": (
            "Run Python (pandas and numpy) for analysis that is awkward in SQL: statistics, "
            "correlations, growth rates, outlier detection, simple forecasts. First the `sql` "
            "query runs and its result is loaded as a pandas DataFrame named `df` (up to "
            f"{MAX_ROWS_FOR_CODE:,} rows). `pd` and `np` are already imported. Only what you "
            "print() is returned, so print concise results. There is no file, network or OS "
            "access, and df.query/df.eval are not available: use boolean masks instead."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query whose result becomes `df`."},
                "code": {"type": "string", "description": "Python code that uses `df` and prints."},
                "purpose": {"type": "string", "description": "One short sentence for the user."},
            },
            "required": ["sql", "code", "purpose"],
            "additionalProperties": False,
        },
    }


def _make_chart_tool() -> BetaToolParam:
    return {
        "name": "make_chart",
        "description": (
            "Create a chart to show the user. The `sql` query should return exactly the data to "
            "plot, already aggregated (e.g. one row per month). `x` and `y` are column names "
            "from that result. Use `color` to split into one series per value of a column (or "
            "an empty string for none). Pick the chart type that fits: line for trends over "
            "time, bar for comparing categories, scatter for relationships, histogram for "
            "distributions, pie only for a few parts of a whole. The chart is shown to the "
            "user automatically."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "chart_type": {"type": "string", "enum": list(CHART_TYPES)},
                "x": {"type": "string", "description": "Column for the x axis (or pie labels)."},
                "y": {
                    "type": "string",
                    "description": "Column for the y axis (or pie values). Empty for histogram.",
                },
                "color": {
                    "type": "string",
                    "description": "Optional column to split series by, or an empty string.",
                },
                "title": {"type": "string"},
            },
            "required": ["sql", "chart_type", "x", "y", "color", "title"],
            "additionalProperties": False,
        },
    }


def text_input(tool_input: Mapping[str, object], key: str) -> str:
    """Read one text field from a tool input.

    Raises:
        ToolInputError: If the field is missing, not text, or too long.
    """
    value = tool_input.get(key)
    if not isinstance(value, str):
        raise ToolInputError(f"Tool input '{key}' must be a string.")
    if len(value) > MAX_INPUT_CHARS:
        raise ToolInputError(f"Tool input '{key}' is longer than {MAX_INPUT_CHARS:,} characters.")
    return value


class ToolExecutor:
    """Runs the tools Claude asks for, against one DataStore."""

    def __init__(self, store: DataStore, limits: SandboxLimits = DEFAULT_LIMITS) -> None:
        self._store = store
        self._limits = limits

    def execute(self, name: str, tool_input: Mapping[str, object]) -> ToolOutcome:
        """Run one tool. Never raises: every failure becomes an error outcome for Claude."""
        try:
            outcome = self._dispatch(name, tool_input)
        except (UnsafeSQLError, SandboxError, ToolInputError, ChartError) as exc:
            # Expected failures: send the message back so Claude can correct itself.
            outcome = ToolOutcome(str(exc), is_error=True)
        except Exception:
            # Fault boundary: a bug in one tool call must not end the whole
            # conversation. Log it for us, report it to Claude, and carry on.
            logger.exception("Tool %s failed", name)
            outcome = ToolOutcome(f"Internal error in tool {name}. Try another approach.", True)
        return limit_content(outcome)

    def _dispatch(self, name: str, tool_input: Mapping[str, object]) -> ToolOutcome:
        match name:
            case "query_database":
                return self._query_database(tool_input)
            case "run_python":
                return self._run_python(tool_input)
            case "make_chart":
                return self._make_chart(tool_input)
            case _:
                return ToolOutcome(f"Unknown tool: {name}", is_error=True)

    def _query_database(self, tool_input: Mapping[str, object]) -> ToolOutcome:
        payload = self._store.run_query(text_input(tool_input, "sql"), MAX_SQL_ROWS_FOR_AGENT)
        require(len(payload["rows"]) <= MAX_SQL_ROWS_FOR_AGENT, "the store returned too many rows")
        if payload["truncated"]:
            payload["note"] = (
                f"Only the first {MAX_SQL_ROWS_FOR_AGENT} rows are shown. "
                "Aggregate in SQL if you need the whole picture."
            )
        return ToolOutcome(json.dumps(payload), display={"result": payload})

    def _run_python(self, tool_input: Mapping[str, object]) -> ToolOutcome:
        sql, code = text_input(tool_input, "sql"), text_input(tool_input, "code")
        df, truncated = self._store.query_df(sql, MAX_ROWS_FOR_CODE)
        require(len(df) <= MAX_ROWS_FOR_CODE, "the store returned too many rows")
        result = run_python(code, df, self._limits)
        text = result.stdout if result.ok else f"{result.stdout}\nERROR:\n{result.error}".strip()
        if truncated:
            text += f"\n(note: df was limited to the first {MAX_ROWS_FOR_CODE:,} rows)"
        return ToolOutcome(text, is_error=not result.ok, display=result.to_display())

    def _make_chart(self, tool_input: Mapping[str, object]) -> ToolOutcome:
        request = ChartRequest(
            chart_type=parse_chart_type(text_input(tool_input, "chart_type")),
            x=text_input(tool_input, "x"),
            y=text_input(tool_input, "y"),
            color=text_input(tool_input, "color"),
            title=text_input(tool_input, "title"),
        )
        df, truncated = self._store.query_df(text_input(tool_input, "sql"), MAX_CHART_POINTS)
        require(len(df) <= MAX_CHART_POINTS, "the store returned too many rows")
        missing = _missing_columns(df, request)
        if missing:
            available = [str(c) for c in df.columns]
            return ToolOutcome(
                f"Column(s) {missing} not in query result. Available: {available}", is_error=True
            )
        chart = build_plotly_spec(df, request)
        note = f" (data truncated to the first {MAX_CHART_POINTS:,} rows)" if truncated else ""
        return ToolOutcome(
            f"Chart '{request.title}' created with {len(df)} rows{note} and shown to the user.",
            chart=chart,
        )


def limit_content(outcome: ToolOutcome) -> ToolOutcome:
    """Cut a tool result that is too long to send back to Claude (rule 3)."""
    if len(outcome.content) <= MAX_RESULT_CHARS:
        return outcome
    note = (
        f"\n[result cut to the first {MAX_RESULT_CHARS:,} of {len(outcome.content):,} characters."
        " Select fewer columns, or aggregate in SQL.]"
    )
    return replace(outcome, content=outcome.content[:MAX_RESULT_CHARS] + note)


def _missing_columns(df: pd.DataFrame, request: ChartRequest) -> list[str]:
    columns = {str(c) for c in df.columns}
    return [c for c in request.needed_columns() if c not in columns]
