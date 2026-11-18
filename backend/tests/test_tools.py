"""Tests for the tools, the chart builder and the Python sandbox."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pandas as pd
import pytest

from app.agent import sandbox
from app.agent.charts import ChartError, ChartRequest, build_plotly_spec, parse_chart_type
from app.agent.sandbox import (
    SandboxError,
    SandboxLimits,
    check_code,
    run_python,
)
from app.agent.tools import (
    MAX_INPUT_CHARS,
    ToolExecutor,
    ToolOutcome,
    limit_content,
    text_input,
    tool_definitions,
)
from app.datastore import DataStore
from app.invariants import InvariantError

# ---------- tool definitions and inputs ----------


def test_tool_definitions_are_strict_and_complete() -> None:
    tools = tool_definitions()
    assert [t["name"] for t in tools] == ["query_database", "run_python", "make_chart"]
    for tool in tools:
        assert tool.get("strict") is True
        schema = tool["input_schema"]
        assert isinstance(schema, dict)
        properties = schema.get("properties")
        assert isinstance(properties, dict)
        assert schema.get("required") == list(properties)
        assert schema.get("additionalProperties") is False


def test_text_input_checks_type_and_length() -> None:
    assert text_input({"sql": "SELECT 1"}, "sql") == "SELECT 1"
    with pytest.raises(ValueError, match="must be a string"):
        _ = text_input({"sql": 1}, "sql")
    with pytest.raises(ValueError, match="must be a string"):
        _ = text_input({}, "sql")
    with pytest.raises(ValueError, match="longer than"):
        _ = text_input({"sql": "x" * (MAX_INPUT_CHARS + 1)}, "sql")


# ---------- the executor ----------


def test_query_tool_truncates_and_says_so(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "query_database", {"sql": "SELECT * FROM sales", "purpose": ""}
    )
    assert out.is_error is False
    payload = json.loads(out.content)
    assert payload["row_count"] == 100
    assert payload["truncated"] is True
    assert "Only the first 100 rows" in payload["note"]


def test_run_python_tool(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "run_python",
        {
            "sql": "SELECT quantity, revenue FROM sales",
            "code": "print(round(df['quantity'].corr(df['revenue']), 2) > 0)",
            "purpose": "correlation",
        },
    )
    assert out.is_error is False
    assert out.content.strip() == "True"
    assert out.display == {"ok": True, "stdout": "True\n", "error": None}


def test_run_python_tool_reports_errors(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "run_python", {"sql": "SELECT 1 AS a", "code": "print('hi')\nprint(1/0)", "purpose": ""}
    )
    assert out.is_error is True
    assert out.content.startswith("hi\nERROR:")
    assert "ZeroDivisionError" in out.content


def test_run_python_tool_notes_truncated_data(
    store: DataStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.agent.tools.MAX_ROWS_FOR_CODE", 10)
    out = ToolExecutor(store).execute(
        "run_python", {"sql": "SELECT * FROM sales", "code": "print(len(df))", "purpose": ""}
    )
    assert out.content == "10\n\n(note: df was limited to the first 10 rows)"


def test_sandbox_rejection_is_a_tool_error(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "run_python", {"sql": "SELECT 1", "code": "import os", "purpose": ""}
    )
    assert out.is_error is True
    assert "not allowed" in out.content


def test_chart_tool(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "make_chart",
        {
            "sql": (
                "SELECT region, channel, SUM(revenue) AS r FROM sales GROUP BY ALL ORDER BY 1, 2"
            ),
            "chart_type": "bar",
            "x": "region",
            "y": "r",
            "color": "channel",
            "title": "Revenue",
        },
    )
    assert out.is_error is False
    assert out.chart is not None
    assert out.chart["layout"].get("barmode") == "group"
    assert "created with 12 rows" in out.content


def test_chart_with_missing_column(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "make_chart",
        {
            "sql": "SELECT region FROM sales",
            "chart_type": "bar",
            "x": "region",
            "y": "nope",
            "color": "",
            "title": "t",
        },
    )
    assert out.is_error
    assert "nope" in out.content


def test_chart_with_bad_type(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "make_chart",
        {
            "sql": "SELECT 1 AS a",
            "chart_type": "radar",
            "x": "a",
            "y": "a",
            "color": "",
            "title": "",
        },
    )
    assert out.is_error
    assert "Unknown chart type" in out.content


def test_chart_tool_notes_truncated_data(store: DataStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agent.tools.MAX_CHART_POINTS", 5)
    out = ToolExecutor(store).execute(
        "make_chart",
        {
            "sql": "SELECT order_id, revenue FROM sales",
            "chart_type": "scatter",
            "x": "order_id",
            "y": "revenue",
            "color": "",
            "title": "t",
        },
    )
    assert "truncated to the first 5 rows" in out.content


def test_unknown_tool(store: DataStore) -> None:
    out = ToolExecutor(store).execute("rm_rf", {})
    assert out.is_error
    assert out.content == "Unknown tool: rm_rf"


def test_unexpected_failure_is_contained(store: DataStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(DataStore, "run_query", broken)
    out = ToolExecutor(store).execute("query_database", {"sql": "SELECT 1", "purpose": ""})
    assert out.is_error
    assert out.content == "Internal error in tool query_database. Try another approach."


# ---------- charts ----------


def chart(chart_type: str, x: str, y: str = "", color: str = "") -> ChartRequest:
    return ChartRequest(chart_type=parse_chart_type(chart_type), x=x, y=y, color=color, title="T")


def test_line_chart_split_by_color() -> None:
    df = pd.DataFrame(
        {
            "m": pd.to_datetime(["2025-01-01", "2025-02-01"] * 2),
            "r": [1, 2, 3, 4],
            "g": ["a", "a", "b", "b"],
        }
    )
    spec = build_plotly_spec(df, chart("line", "m", "r", "g"))
    assert [t.get("name") for t in spec["data"]] == ["a", "b"]
    assert spec["data"][0].get("x") == ["2025-01-01", "2025-02-01"]
    assert spec["data"][0].get("mode") == "lines+markers"
    assert spec["layout"]["title"] == {"text": "T"}


def test_dates_keep_their_time_of_day() -> None:
    df = pd.DataFrame({"t": pd.to_datetime(["2025-01-01 10:30", "2025-01-01 11:00"]), "v": [1, 2]})
    spec = build_plotly_spec(df, chart("scatter", "t", "v"))
    assert spec["data"][0].get("x") == ["2025-01-01T10:30:00", "2025-01-01T11:00:00"]
    assert spec["data"][0].get("mode") == "markers"


def test_pie_and_histogram() -> None:
    df = pd.DataFrame({"k": ["a", "b"], "v": [1.5, None]})
    pie = build_plotly_spec(df, chart("pie", "k", "v"))
    assert pie["data"] == [{"type": "pie", "labels": ["a", "b"], "values": [1.5, None]}]
    assert "xaxis" not in pie["layout"]
    hist = build_plotly_spec(df, chart("histogram", "v"))
    assert hist["data"] == [{"type": "histogram", "x": [1.5, None]}]
    assert hist["layout"].get("yaxis") == {"title": {"text": "count"}}


def test_missing_color_values_get_a_label() -> None:
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4], "g": ["a", None]})
    spec = build_plotly_spec(df, chart("bar", "x", "y", "g"))
    assert [t.get("name") for t in spec["data"]] == ["a", "(missing)"]


def test_too_many_series() -> None:
    df = pd.DataFrame({"x": range(30), "y": range(30), "g": [str(i) for i in range(30)]})
    with pytest.raises(ChartError, match="at most 25 series"):
        _ = build_plotly_spec(df, chart("bar", "x", "y", "g"))


def test_columns_must_be_checked_first() -> None:
    df = pd.DataFrame({"x": [1]})
    with pytest.raises(InvariantError):
        _ = build_plotly_spec(df, chart("bar", "x", "missing"))


def test_unknown_chart_type() -> None:
    with pytest.raises(ChartError):
        _ = parse_chart_type("radar")


# ---------- sandbox: static check ----------


@pytest.mark.parametrize(
    "code",
    [
        "import os",
        "import subprocess",
        "from socket import socket",
        "from . import x",
        "open('/etc/passwd')",
        "__import__('os')",
        "eval('1')",
        "df.to_csv('x')",
        "().__class__.__bases__",
        "getattr(df, 'to_csv')",
        "df._mgr",
        "pd.io.common",
        "np.load('x.npy')",
        "df.query('a > 1')",
        "x = '{0.__class__}'.format(df)",
        "print(__builtins__)",
        "def f(:\n  pass",
        "x = 1\n" * 10_001,
    ],
)
def test_sandbox_blocks(code: str) -> None:
    with pytest.raises(SandboxError):
        check_code(code)


@pytest.mark.parametrize(
    "code",
    [
        "import pandas as pd\nimport numpy as np",
        "from collections import Counter",
        "import numpy.linalg",
        "print(df.groupby('a')['b'].agg(['sum', 'mean']))",
        "x = [i * 2 for i in range(10)]",
    ],
)
def test_sandbox_allows_ordinary_analysis(code: str) -> None:
    check_code(code)


# ---------- sandbox: running code ----------


def test_sandbox_runs_and_returns_output() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = run_python("import json, statistics\nprint(json.dumps(statistics.mean(df['a'])))", df)
    assert result.ok
    assert result.stdout == "2\n"


def test_sandbox_without_output_says_so() -> None:
    result = run_python("x = 1", pd.DataFrame())
    assert result.ok
    assert "use print()" in result.stdout


def test_sandbox_error_keeps_printed_output() -> None:
    result = run_python("print('before')\nprint(1/0)", pd.DataFrame({"a": [1]}))
    assert not result.ok
    assert result.stdout == "before"
    assert result.error is not None
    assert 'File "user_code.py", line 2' in result.error
    assert result.error.endswith("ZeroDivisionError: division by zero")
    assert "runner.py" not in result.error


def test_sandbox_timeout() -> None:
    limits = SandboxLimits(timeout_s=1, cpu_s=30)
    code = "import itertools\nfor _ in itertools.count():\n    pass"
    result = run_python(code, pd.DataFrame({"a": [1]}), limits)
    assert result.error == "Timed out after 1s."


def test_sandbox_cpu_limit() -> None:
    limits = SandboxLimits(timeout_s=20, cpu_s=1)
    result = run_python("x = 0\nfor i in range(10**10):\n    x += i", pd.DataFrame(), limits)
    assert result.error == "Stopped: used more than 1s of CPU time."


def test_sandbox_memory_limit() -> None:
    limits = SandboxLimits(memory_mb=512)
    result = run_python("a = np.ones((100, 1000, 1000))\nprint(a.sum())", pd.DataFrame(), limits)
    assert not result.ok
    assert result.error is not None
    assert "out of memory" in result.error


def test_sandbox_output_limit() -> None:
    limits = SandboxLimits(output_bytes=1000)
    result = run_python("print('x' * 5000)", pd.DataFrame(), limits)
    assert result.error == "Too much output: print less."
    assert len(result.stdout) == 1000


def test_sandbox_long_output_is_truncated() -> None:
    result = run_python("print('y' * 9000)", pd.DataFrame())
    assert result.ok
    assert "output truncated, 9,001 characters total" in result.stdout


def test_sandbox_cannot_write_or_open_files(tmp_path: Path) -> None:
    target = tmp_path / "precious.txt"
    _ = target.write_text("keep me", encoding="utf-8")
    # String dispatch gets past the syntax check, so the OS limits must stop it.
    code = f"df.agg('to_string', buf={str(target)!r})"
    result = run_python(code, pd.DataFrame({"a": [1]}))
    assert not result.ok
    assert result.error is not None
    assert "no file or network access" in result.error
    assert target.read_text(encoding="utf-8") == "keep me"


def test_sandbox_error_without_traceback() -> None:
    printed, error = sandbox._split_traceback("some output\nKilled")
    assert (printed, error) == ("", "some output\nKilled")
    assert sandbox._split_traceback("") == ("", "The code failed.")


def test_signal_messages() -> None:
    limits = SandboxLimits()
    assert "CPU time" in sandbox._signal_message(-signal.SIGXCPU, limits)
    assert "memory or CPU" in sandbox._signal_message(-signal.SIGKILL, limits)
    assert (
        sandbox._signal_message(-signal.SIGSEGV, limits) == f"Stopped by signal {signal.SIGSEGV}."
    )


def test_sandbox_refuses_to_run_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    with pytest.raises(SandboxError, match="Linux or macOS"):
        _ = run_python("print(1)", pd.DataFrame())


def test_chart_requests_name_their_columns() -> None:
    with pytest.raises(ChartError, match="`x` must name a column"):
        _ = chart("bar", "")
    with pytest.raises(ChartError, match="A bar chart needs `y`"):
        _ = chart("bar", "region")
    assert chart("histogram", "revenue").needed_columns() == ["revenue"]


def test_chart_tool_explains_a_missing_y(store: DataStore) -> None:
    out = ToolExecutor(store).execute(
        "make_chart",
        {"sql": "SELECT 1 AS a", "chart_type": "line", "x": "a", "y": "", "color": "", "title": ""},
    )
    assert out.is_error is True
    assert "needs `y`" in out.content


def test_long_tool_results_are_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agent.tools.MAX_RESULT_CHARS", 10)
    short = ToolOutcome("0123456789")
    assert limit_content(short) is short
    cut = limit_content(ToolOutcome("0123456789abc", is_error=True))
    assert cut.content.startswith("0123456789\n[result cut to the first 10 of 13 characters.")
    assert cut.is_error is True


def test_long_query_results_reach_claude_cut(
    store: DataStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.agent.tools.MAX_RESULT_CHARS", 100)
    out = ToolExecutor(store).execute("query_database", {"sql": "SELECT * FROM sales"})
    assert "[result cut to the first 100 of" in out.content
    result = out.display["result"]
    assert isinstance(result, dict)
    assert len(result["rows"]) == 100


@pytest.mark.parametrize("field", ["timeout_s", "cpu_s", "memory_mb", "output_bytes"])
def test_sandbox_limits_must_be_positive(field: str) -> None:
    with pytest.raises(InvariantError, match=f"{field} must be positive"):
        _ = SandboxLimits(**{field: 0})


def test_signal_message_needs_a_signal() -> None:
    with pytest.raises(InvariantError, match="negative"):
        _ = sandbox._signal_message(1, SandboxLimits())
