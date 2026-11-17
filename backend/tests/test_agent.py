"""Agent tests with a *fake* Claude client.

We script Claude's replies, so the tests are free, fast and deterministic.
They check OUR code: that tool calls are executed, results are sent back in the
right shape, errors are recoverable, and the loop stops.
"""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.agent.orchestrator import DataAnalystAgent
from app.agent.sandbox import SandboxError, check_code, run_python
from app.agent.tools import TOOL_DEFINITIONS, ToolExecutor, build_plotly_spec
from app.datastore import DataStore
from app.main import create_app

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_sales.csv"


# ---------- a fake Anthropic client ----------

def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, **inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Copy the message list: the agent keeps appending to the same list.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


@pytest.fixture
def store():
    s = DataStore(":memory:")
    s.load_csv("sales.csv", SAMPLE.read_bytes())
    return s


# ---------- the loop ----------

def test_agent_runs_tools_and_answers(store):
    client = FakeClient([
        reply(tool_use("t1", "query_database",
                       sql="SELECT region, SUM(revenue) AS r FROM sales GROUP BY 1 ORDER BY 2 DESC",
                       purpose="Revenue by region")),
        reply(tool_use("t2", "make_chart", sql="SELECT region, SUM(revenue) AS r FROM sales GROUP BY 1",
                       chart_type="bar", x="region", y="r", color="", title="Revenue by region")),
        reply(text("West had the most revenue."), stop="end_turn"),
    ])
    events = list(DataAnalystAgent(store, client=client).run("Which region sells most?"))

    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_result", "tool_call", "tool_result", "answer"]
    answer = events[-1]
    assert answer["text"] == "West had the most revenue."
    assert len(answer["charts"]) == 1 and answer["charts"][0]["data"][0]["type"] == "bar"

    # The schema was given to Claude in the system prompt.
    first = client.calls[0]
    assert "Table `sales`" in first["system"] and "revenue (DOUBLE)" in first["system"]
    assert first["tools"] == TOOL_DEFINITIONS
    # The tool result went back as a user message with the matching tool_use_id.
    second_msgs = client.calls[1]["messages"]
    result_block = second_msgs[-1]["content"][0]
    assert second_msgs[-1]["role"] == "user"
    assert result_block["tool_use_id"] == "t1" and result_block["is_error"] is False
    assert "North" in result_block["content"]


def test_sql_error_is_sent_back_so_agent_can_fix_it(store):
    client = FakeClient([
        reply(tool_use("t1", "query_database", sql="SELECT revenu FROM sales", purpose="x")),
        reply(tool_use("t2", "query_database", sql="SELECT SUM(revenue) FROM sales", purpose="x")),
        reply(text("Done."), stop="end_turn"),
    ])
    events = list(DataAnalystAgent(store, client=client).run("total?"))
    first_result = events[1]
    assert first_result["is_error"] is True and "revenu" in first_result["content"]
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert events[-1]["type"] == "answer"


def test_parallel_tool_calls_return_in_one_message(store):
    client = FakeClient([
        reply(
            tool_use("a", "query_database", sql="SELECT COUNT(*) FROM sales", purpose="x"),
            tool_use("b", "query_database", sql="SELECT MAX(revenue) FROM sales", purpose="y"),
        ),
        reply(text("ok"), stop="end_turn"),
    ])
    list(DataAnalystAgent(store, client=client).run("q"))
    results = client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_agent_stops_after_max_steps(store):
    loop = [reply(tool_use(f"t{i}", "query_database", sql="SELECT 1", purpose="x")) for i in range(3)]
    events = list(DataAnalystAgent(store, client=FakeClient(loop), max_steps=3).run("q"))
    assert events[-1]["type"] == "error" and "3 steps" in events[-1]["message"]


def test_refusal_is_reported(store):
    client = FakeClient([reply(stop="refusal")])
    events = list(DataAnalystAgent(store, client=client).run("q"))
    assert events[-1]["type"] == "error"


def test_no_datasets():
    events = list(DataAnalystAgent(DataStore(), client=FakeClient([])).run("q"))
    assert events == [{"type": "error", "message": "No datasets uploaded yet. Upload a CSV first."}]


# ---------- tools ----------

def test_run_python_tool(store):
    out = ToolExecutor(store).execute("run_python", {
        "sql": "SELECT quantity, revenue FROM sales",
        "code": "print(round(df['quantity'].corr(df['revenue']), 2) > 0)",
        "purpose": "correlation",
    })
    assert out.is_error is False and out.content.strip() == "True"


def test_chart_with_missing_column(store):
    out = ToolExecutor(store).execute("make_chart", {
        "sql": "SELECT region FROM sales", "chart_type": "bar", "x": "region", "y": "nope",
        "color": "", "title": "t",
    })
    assert out.is_error and "nope" in out.content


def test_unknown_tool(store):
    assert ToolExecutor(store).execute("rm_rf", {}).is_error


def test_line_chart_split_by_color():
    df = pd.DataFrame({"m": pd.to_datetime(["2025-01-01", "2025-02-01"] * 2),
                       "r": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]})
    spec = build_plotly_spec(df, "line", "m", "r", "g", "T")
    assert [t["name"] for t in spec["data"]] == ["a", "b"]
    assert spec["data"][0]["x"] == ["2025-01-01", "2025-02-01"]
    assert spec["data"][0]["mode"] == "lines+markers"


# ---------- sandbox ----------

@pytest.mark.parametrize("code", [
    "import os", "import subprocess", "from socket import socket", "open('/etc/passwd')",
    "__import__('os')", "eval('1')", "df.to_csv('x')", "().__class__.__bases__",
    "getattr(df, 'to_csv')",
])
def test_sandbox_blocks(code):
    with pytest.raises(SandboxError):
        check_code(code)


def test_sandbox_timeout_and_errors():
    df = pd.DataFrame({"a": [1]})
    assert "Timed out" in run_python("while True:\n    pass", df, timeout_s=2).error
    res = run_python("print(1/0)", df)
    assert not res.ok and "ZeroDivisionError" in res.error


# ---------- API ----------

def test_ask_endpoint_with_fake_agent():
    client = FakeClient([reply(text("42 orders."), stop="end_turn")])
    app = create_app(DataStore(":memory:"), agent_factory=lambda s: DataAnalystAgent(s, client=client))
    api = TestClient(app)
    api.post("/datasets", files={"file": ("sales.csv", SAMPLE.read_bytes(), "text/csv")})
    body = api.post("/ask", json={"question": "How many orders?"}).json()
    assert body == {"ok": True, "answer": "42 orders.", "charts": [], "steps": []}
    assert api.post("/ask", json={"question": "hi?", "datasets": ["nope"]}).status_code == 404


def test_ask_without_api_key_returns_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    api = TestClient(create_app(DataStore(":memory:")))  # the real agent factory
    assert api.post("/ask", json={"question": "anything?"}).status_code == 503
