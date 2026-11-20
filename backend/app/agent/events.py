"""The events the agent reports while it works.

Every step of the agent becomes one event: a thought, a note, a tool call, a
tool result, and finally an answer or an error. The CLI prints them, the API
returns them, and the chat UI will show them live. Each event is a plain dict
(a `TypedDict`), so it turns into JSON without any conversion.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from app.agent.charts import Chart


class ThinkingEvent(TypedDict):
    """A summary of the model's reasoning."""

    type: Literal["thinking"]
    text: str


class NoteEvent(TypedDict):
    """Something the model said between tool calls."""

    type: Literal["note"]
    text: str


class ToolCallEvent(TypedDict):
    """The model asked to run a tool."""

    type: Literal["tool_call"]
    id: str
    name: str
    input: dict[str, object]


class ToolResultEvent(TypedDict):
    """What a tool returned."""

    type: Literal["tool_result"]
    id: str
    name: str
    is_error: bool
    content: str
    display: dict[str, object]
    chart: Chart | None


class AnswerEvent(TypedDict):
    """The final answer. Always the last event of a successful run."""

    type: Literal["answer"]
    text: str
    charts: list[Chart]
    steps: int


class ErrorEvent(TypedDict):
    """The run stopped without an answer. Always the last event of a failed run."""

    type: Literal["error"]
    message: str
    charts: list[Chart]


type FinalEvent = AnswerEvent | ErrorEvent
type AgentEvent = ThinkingEvent | NoteEvent | ToolCallEvent | ToolResultEvent | FinalEvent


def error_event(message: str, charts: list[Chart] | None = None) -> ErrorEvent:
    """Build an error event."""
    return ErrorEvent(type="error", message=message, charts=list(charts or []))
