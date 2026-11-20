"""Tests for the Claude client: the exact request we send, and error handling.

The SDK talks to a fake HTTP transport here, so we check the real request the
SDK builds (URL, headers, JSON body) without any network access.
"""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest

from app.agent.llm import (
    DEFAULT_MODEL,
    FALLBACK_BETA,
    AgentConfigError,
    ClaudeClient,
    ClaudeSettings,
    LLMError,
    claude_client_from_env,
    parse_effort,
    settings_from_env,
)
from app.agent.tools import tool_definitions
from app.invariants import InvariantError

REPLY_JSON = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-5-5",
    "content": [{"type": "text", "text": "Hello"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 3, "output_tokens": 1},
}


class Recorder:
    """A fake HTTP server: records each request and answers with a fixed response."""

    def __init__(self, status: int = 200, body: object = None) -> None:
        self.status = status
        self.body = REPLY_JSON if body is None else body
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, json=self.body)

    def client(self, settings: ClaudeSettings | None = None) -> ClaudeClient:
        transport = httpx2.MockTransport(self.handle)
        sdk = anthropic.Anthropic(
            api_key="test-key", http_client=httpx2.Client(transport=transport), max_retries=0
        )
        return ClaudeClient(sdk, settings or ClaudeSettings())


def test_request_has_the_expected_shape() -> None:
    server = Recorder()
    client = server.client(ClaudeSettings(model="m-1", effort="high", max_tokens=123))
    message = client.create_message(
        "system text", [{"role": "user", "content": "hi"}], tool_definitions()
    )

    assert message.content[0].type == "text"
    request = server.requests[0]
    assert request.url.path == "/v1/messages"
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    body = json.loads(request.content)
    assert body["model"] == "m-1"
    assert body["max_tokens"] == 123
    assert body["system"] == "system text"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert [t["name"] for t in body["tools"]] == ["query_database", "run_python", "make_chart"]
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "high"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["fallbacks"] == "default"


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Invalid or missing ANTHROPIC_API_KEY."),
        (429, "Rate limited by the Claude API. Try again shortly."),
        (500, "Claude API error (500)"),
    ],
)
def test_api_errors_become_llm_errors(status: int, message: str) -> None:
    error = {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    client = Recorder(status, error).client()
    with pytest.raises(LLMError, match=message.replace("(", r"\(").replace(")", r"\)")):
        _ = client.create_message("s", [{"role": "user", "content": "hi"}], [])


def test_connection_errors_become_llm_errors() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    sdk = anthropic.Anthropic(
        api_key="k",
        http_client=httpx2.Client(transport=httpx2.MockTransport(refuse)),
        max_retries=0,
    )
    with pytest.raises(LLMError, match="Could not reach"):
        _ = ClaudeClient(sdk, ClaudeSettings()).create_message("s", [], [])


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings_from_env() == ClaudeSettings(model=DEFAULT_MODEL, effort="medium")
    monkeypatch.setenv("ANTHROPIC_MODEL", "other-model")
    monkeypatch.setenv("AGENT_EFFORT", "low")
    assert settings_from_env() == ClaudeSettings(model="other-model", effort="low")


@pytest.mark.parametrize("value", ["low", "medium", "high", "xhigh", "max"])
def test_parse_effort_accepts_known_levels(value: str) -> None:
    assert parse_effort(value) == value


def test_parse_effort_rejects_unknown_levels() -> None:
    with pytest.raises(AgentConfigError, match="AGENT_EFFORT"):
        _ = parse_effort("extreme")


def test_client_from_env_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(AgentConfigError, match="ANTHROPIC_API_KEY is not set"):
        _ = claude_client_from_env()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(claude_client_from_env(), ClaudeClient)


def test_settings_are_checked() -> None:
    with pytest.raises(InvariantError, match="model name must not be empty"):
        _ = ClaudeSettings(model=" ")
    with pytest.raises(InvariantError, match="max_tokens must be positive"):
        _ = ClaudeSettings(max_tokens=0)
