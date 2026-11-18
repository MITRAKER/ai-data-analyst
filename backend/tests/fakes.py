"""Test doubles: a scripted Claude, and helpers that build real SDK reply objects.

We script Claude's replies, so the tests are free, fast and deterministic.
They check OUR code: that tool calls are executed, results are sent back in the
right shape, errors are recoverable, and the loop stops.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass

from anthropic.types.beta import (
    BetaContentBlock,
    BetaFallbackBlock,
    BetaMessage,
    BetaMessageParam,
    BetaStopReason,
    BetaTextBlock,
    BetaThinkingBlock,
    BetaToolParam,
    BetaToolUseBlock,
    BetaUsage,
)
from anthropic.types.beta.beta_fallback_info import BetaFallbackInfo
from anthropic.types.beta.beta_fallback_refusal_trigger import BetaFallbackRefusalTrigger

from app.agent.llm import LLMError


def text(value: str) -> BetaTextBlock:
    return BetaTextBlock(type="text", text=value)


def thinking(value: str) -> BetaThinkingBlock:
    return BetaThinkingBlock(type="thinking", thinking=value, signature="sig")


def tool_use(id_: str, name: str, **tool_input: object) -> BetaToolUseBlock:
    return BetaToolUseBlock(type="tool_use", id=id_, name=name, input=tool_input)


def fallback(from_model: str, to_model: str) -> BetaFallbackBlock:
    return BetaFallbackBlock.model_validate(
        {
            "type": "fallback",
            "from": BetaFallbackInfo(model=from_model),
            "to": BetaFallbackInfo(model=to_model),
            "trigger": BetaFallbackRefusalTrigger(type="refusal"),
        }
    )


def reply(*blocks: BetaContentBlock, stop: BetaStopReason = "tool_use") -> BetaMessage:
    return BetaMessage(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-opus-5-5",
        content=list(blocks),
        stop_reason=stop,
        usage=BetaUsage(input_tokens=10, output_tokens=5),
    )


@dataclass
class Call:
    system: str
    messages: list[BetaMessageParam]
    tools: list[BetaToolParam]


class FakeLLM:
    """An LLMClient that returns scripted replies (or raises scripted errors)."""

    def __init__(self, replies: Sequence[BetaMessage | LLMError]) -> None:
        self.replies = list(replies)
        self.calls: list[Call] = []

    def create_message(
        self, system: str, messages: list[BetaMessageParam], tools: list[BetaToolParam]
    ) -> BetaMessage:
        # Copy the messages: the agent keeps appending to the same list.
        self.calls.append(Call(system, copy.deepcopy(messages), tools))
        next_reply = self.replies.pop(0)
        if isinstance(next_reply, LLMError):
            raise next_reply
        return next_reply


def opening_text(call: Call) -> str:
    """The text of the first user message: the dataset descriptions and the question."""
    content = call.messages[0].get("content")
    assert isinstance(content, str)
    return content


def sent_tool_results(call: Call) -> list[dict[str, object]]:
    """The tool_result blocks in the last message of a request."""
    last = call.messages[-1]
    assert last.get("role") == "user"
    content = last.get("content")
    assert isinstance(content, list)
    return [dict(block) for block in content if isinstance(block, dict)]
