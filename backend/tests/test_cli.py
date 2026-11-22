"""Tests for the terminal CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.events import AgentEvent
from app.cli import main, render
from tests.conftest import SAMPLE
from tests.fakes import FakeLLM, reply, text, thinking, tool_use


def test_cli_answers_and_saves_charts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    llm = FakeLLM(
        [
            reply(
                thinking("Plan."),
                text("Checking."),
                tool_use(
                    "t", "query_database", sql="SELECT COUNT(*) FROM sales_data", purpose="Count"
                ),
                tool_use(
                    "c",
                    "make_chart",
                    sql="SELECT region, SUM(revenue) AS r FROM sales_data GROUP BY 1",
                    chart_type="bar",
                    x="region",
                    y="r",
                    color="",
                    title="Revenue",
                ),
            ),
            reply(text("2,000 orders."), stop="end_turn"),
        ]
    )
    csv = tmp_path / "sales data.csv"
    _ = csv.write_bytes(SAMPLE.read_bytes())

    assert main([str(csv), "How many orders?"], llm=llm) == 0

    out = capsys.readouterr().out
    assert "Loaded" in out
    assert "table `sales_data` (2,000 rows)" in out
    assert "Answer" in out
    assert "2,000 orders." in out
    chart = json.loads((tmp_path / "chart_1.json").read_text(encoding="utf-8"))
    assert chart["data"][0]["type"] == "bar"


def test_cli_reports_agent_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv = tmp_path / "s.csv"
    _ = csv.write_bytes(b"a\n1\n")
    assert main([str(csv), "q?"], llm=FakeLLM([reply(stop="refusal")])) == 1
    assert "Error: The model declined" in capsys.readouterr().out


def test_cli_needs_a_csv_and_a_question(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["only a question"]) == 2
    assert "at least one CSV" in capsys.readouterr().out


def test_cli_reports_missing_files(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["/no/such/file.csv", "q?"], llm=FakeLLM([])) == 2
    assert "no such file" in capsys.readouterr().out


def test_cli_rejects_huge_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.cli.MAX_UPLOAD_BYTES", 1)
    csv = tmp_path / "s.csv"
    _ = csv.write_bytes(b"a\n1\n")
    assert main([str(csv), "q?"], llm=FakeLLM([])) == 2
    assert "larger than" in capsys.readouterr().out


def test_cli_without_api_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv = tmp_path / "s.csv"
    _ = csv.write_bytes(b"a\n1\n")
    assert main([str(csv), "q?"]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out


def test_render_shows_code_and_long_results() -> None:
    call: AgentEvent = {
        "type": "tool_call",
        "id": "1",
        "name": "run_python",
        "input": {"purpose": "Stats", "sql": "SELECT 1", "code": "a = 1\nprint(a)"},
    }
    rendered = render(call)
    assert "run_python" in rendered
    assert "Stats" in rendered
    assert "SELECT 1" in rendered
    assert "  print(a)" in rendered
    result: AgentEvent = {
        "type": "tool_result",
        "id": "1",
        "name": "run_python",
        "is_error": True,
        "content": "x" * 600,
        "display": {},
        "chart": None,
    }
    assert render(result).count("x") == 500
