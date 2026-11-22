"""Tests for the agent loop (orchestrator), using the scripted FakeLLM."""

from __future__ import annotations

import json

import pytest

from app.agent.events import AgentEvent
from app.agent.llm import LLMError
from app.agent.orchestrator import (
    MAX_TOOL_CALLS_PER_STEP,
    SYSTEM_PROMPT,
    DataAnalystAgent,
    final_event,
    first_message,
)
from app.agent.tools import tool_definitions
from app.datastore import DataStore
from app.invariants import InvariantError
from tests.fakes import (
    FakeLLM,
    fallback,
    opening_text,
    reply,
    sent_tool_results,
    text,
    thinking,
    tool_use,
)


def run(store: DataStore, llm: FakeLLM, question: str = "q") -> list[AgentEvent]:
    return list(DataAnalystAgent(store, llm).run(question))


def test_agent_runs_tools_and_answers(store: DataStore) -> None:
    llm = FakeLLM(
        [
            reply(
                thinking("Compare regions."),
                text("Let me check."),
                tool_use(
                    "t1",
                    "query_database",
                    sql="SELECT region, SUM(revenue) AS r FROM sales GROUP BY 1 ORDER BY 2 DESC",
                    purpose="Revenue by region",
                ),
            ),
            reply(
                tool_use(
                    "t2",
                    "make_chart",
                    sql="SELECT region, SUM(revenue) AS r FROM sales GROUP BY 1",
                    chart_type="bar",
                    x="region",
                    y="r",
                    color="",
                    title="Revenue by region",
                )
            ),
            reply(text("West had the most revenue."), stop="end_turn"),
        ]
    )
    events = run(store, llm, "Which region sells most?")

    types = [e["type"] for e in events]
    assert types == [
        "thinking",
        "note",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "answer",
    ]
    answer = events[-1]
    assert answer["type"] == "answer"
    assert answer["text"] == "West had the most revenue."
    assert answer["steps"] == 3
    assert len(answer["charts"]) == 1
    assert answer["charts"][0]["data"][0]["type"] == "bar"

    # The system prompt is fixed; the datasets and the question are in the first message.
    first = llm.calls[0]
    assert first.system == SYSTEM_PROMPT
    assert first.tools == tool_definitions()
    opening = opening_text(first)
    assert "Table `sales`" in opening
    assert "revenue (DOUBLE)" in opening
    assert opening.endswith("<question>\nWhich region sells most?\n</question>")

    # The tool result went back as a user message with the matching tool_use_id.
    result = sent_tool_results(llm.calls[1])[0]
    assert result["tool_use_id"] == "t1"
    assert result["is_error"] is False
    assert "North" in str(result["content"])


def test_sql_error_is_sent_back_so_agent_can_fix_it(store: DataStore) -> None:
    llm = FakeLLM(
        [
            reply(tool_use("t1", "query_database", sql="SELECT revenu FROM sales", purpose="x")),
            reply(
                tool_use("t2", "query_database", sql="SELECT SUM(revenue) FROM sales", purpose="x")
            ),
            reply(text("Done."), stop="end_turn"),
        ]
    )
    events = run(store, llm, "total?")
    first_result = events[1]
    assert first_result["type"] == "tool_result"
    assert first_result["is_error"] is True
    assert "revenu" in first_result["content"]
    assert sent_tool_results(llm.calls[1])[0]["is_error"] is True
    assert events[-1]["type"] == "answer"


def test_parallel_tool_calls_return_in_one_message(store: DataStore) -> None:
    llm = FakeLLM(
        [
            reply(
                tool_use("a", "query_database", sql="SELECT COUNT(*) FROM sales", purpose="x"),
                tool_use("b", "query_database", sql="SELECT MAX(revenue) FROM sales", purpose="y"),
            ),
            reply(text("ok"), stop="end_turn"),
        ]
    )
    _ = run(store, llm)
    assert [r["tool_use_id"] for r in sent_tool_results(llm.calls[1])] == ["a", "b"]


def test_too_many_tool_calls_in_one_step_are_skipped(store: DataStore) -> None:
    calls = [
        tool_use(f"t{i}", "query_database", sql="SELECT 1", purpose="x")
        for i in range(MAX_TOOL_CALLS_PER_STEP + 2)
    ]
    llm = FakeLLM([reply(*calls), reply(text("ok"), stop="end_turn")])
    events = run(store, llm)
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == MAX_TOOL_CALLS_PER_STEP + 2
    assert [r["is_error"] for r in results[-2:]] == [True, True]
    assert "Skipped" in results[-1]["content"]


def test_agent_stops_after_max_steps(store: DataStore) -> None:
    loop = [
        reply(tool_use(f"t{i}", "query_database", sql="SELECT 1", purpose="x")) for i in range(3)
    ]
    events = list(DataAnalystAgent(store, FakeLLM(loop), max_steps=3).run("q"))
    final = events[-1]
    assert final["type"] == "error"
    assert "3 steps" in final["message"]


@pytest.mark.parametrize("max_steps", [0, 51])
def test_max_steps_must_be_in_range(store: DataStore, max_steps: int) -> None:
    with pytest.raises(InvariantError):
        _ = DataAnalystAgent(store, FakeLLM([]), max_steps=max_steps)


def test_refusal_is_reported(store: DataStore) -> None:
    events = run(store, FakeLLM([reply(stop="refusal")]))
    assert events[-1] == {
        "type": "error",
        "message": "The model declined to answer this request.",
        "charts": [],
    }


def test_llm_error_is_reported(store: DataStore) -> None:
    events = run(store, FakeLLM([LLMError("Could not reach the Claude API.")]))
    assert events == [{"type": "error", "message": "Could not reach the Claude API.", "charts": []}]


def test_cut_off_answer_says_so(store: DataStore) -> None:
    events = run(store, FakeLLM([reply(text("Partial"), stop="max_tokens")]))
    final = events[-1]
    assert final["type"] == "answer"
    assert final["text"].startswith("Partial")
    assert "cut off" in final["text"]


def test_pause_turn_continues_the_conversation(store: DataStore) -> None:
    llm = FakeLLM([reply(text("Working"), stop="pause_turn"), reply(text("Done"), stop="end_turn")])
    events = run(store, llm)
    assert events[-1]["type"] == "answer"
    assert len(llm.calls) == 2
    assert llm.calls[1].messages[-1].get("role") == "assistant"


def test_tool_use_without_tool_block_is_an_error(store: DataStore) -> None:
    events = run(store, FakeLLM([reply(text("hmm"), stop="tool_use")]))
    final = events[-1]
    assert final["type"] == "error"
    assert "did not name" in final["message"]


def test_fallback_model_is_mentioned(store: DataStore) -> None:
    llm = FakeLLM([reply(fallback("claude-opus-5-5", "other-model"), text("Hi"), stop="end_turn")])
    events = run(store, llm)
    assert events[0] == {
        "type": "note",
        "text": "The request was answered by other-model instead of claude-opus-5-5.",
    }


def test_empty_thinking_and_text_are_not_reported(store: DataStore) -> None:
    llm = FakeLLM(
        [
            reply(
                thinking(""),
                text("  "),
                tool_use("t", "query_database", sql="SELECT 1", purpose=""),
            ),
            reply(text("ok"), stop="end_turn"),
        ]
    )
    assert [e["type"] for e in run(store, llm)] == ["tool_call", "tool_result", "answer"]


def test_no_datasets() -> None:
    events = list(DataAnalystAgent(DataStore(), FakeLLM([])).run("q"))
    assert events == [
        {"type": "error", "message": "No datasets uploaded yet. Upload a CSV first.", "charts": []}
    ]


def test_only_the_requested_tables_are_described(store: DataStore) -> None:
    _ = store.load_csv("other.csv", b"a,b\n1,2\n")
    llm = FakeLLM([reply(text("ok"), stop="end_turn")])
    _ = list(DataAnalystAgent(store, llm).run("q", ["other"]))
    opening = opening_text(llm.calls[0])
    assert "Table `other`" in opening
    assert "Table `sales`" not in opening


def test_first_message_keeps_data_and_question_apart() -> None:
    message = first_message("Why?", "Table `t`")
    assert message == "<datasets>\nTable `t`\n</datasets>\n\n<question>\nWhy?\n</question>"


def test_chart_json_is_serializable(store: DataStore) -> None:
    llm = FakeLLM(
        [
            reply(
                tool_use(
                    "c",
                    "make_chart",
                    sql="SELECT date_trunc('month', order_date) AS m, SUM(revenue) AS r "
                    "FROM sales GROUP BY 1 ORDER BY 1",
                    chart_type="line",
                    x="m",
                    y="r",
                    color="",
                    title="Monthly revenue",
                )
            ),
            reply(text("ok"), stop="end_turn"),
        ]
    )
    final = run(store, llm)[-1]
    assert final["type"] == "answer"
    chart = final["charts"][0]
    assert json.loads(json.dumps(chart)) == chart
    assert chart["data"][0].get("x", [])[:1] == ["2025-01-01"]


def test_the_question_must_not_be_empty() -> None:
    with pytest.raises(InvariantError, match="question must not be empty"):
        _ = first_message("  ", "schema")


def test_steps_are_counted_from_one() -> None:
    with pytest.raises(InvariantError, match="counted from 1"):
        _ = final_event(reply(text("hi"), stop="end_turn"), [], 0)
