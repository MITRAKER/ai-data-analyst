"""The connection to Claude, behind a small interface.

The agent needs one thing from the outside world: "send this conversation to
the model and give me its reply". `LLMClient` describes exactly that and
nothing more. `ClaudeClient` is the real one: it calls the Anthropic API with
this app's settings. Tests pass a scripted fake instead, so they run without
network access, cost or an API key.

Passing an object that implements an interface (a `Protocol`) is how this
code swaps behavior without passing functions around (Power of Ten rule 9).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaToolParam

from app.invariants import require

DEFAULT_MODEL: Final = "claude-opus-5-5"
MAX_TOKENS: Final = 16_000
REQUEST_TIMEOUT_S: Final = 300.0
# If the model declines a request, the API retries it on a fallback model.
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"

type Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AgentConfigError(RuntimeError):
    """The agent cannot run: a setting such as the API key is missing or invalid."""


class LLMError(RuntimeError):
    """A request to the model failed. The message is safe to show to the user."""


class LLMClient(Protocol):
    """Anything that can send a conversation to the model and return its reply."""

    def create_message(
        self, system: str, messages: list[BetaMessageParam], tools: list[BetaToolParam]
    ) -> BetaMessage:
        """Send one request and return the model's reply.

        Raises:
            LLMError: If the request fails.
        """
        ...


@dataclass(frozen=True, slots=True)
class ClaudeSettings:
    """Which model to use and how hard it should think."""

    model: str = DEFAULT_MODEL
    effort: Effort = "medium"
    max_tokens: int = MAX_TOKENS

    def __post_init__(self) -> None:
        require(bool(self.model.strip()), "the model name must not be empty")
        require(self.max_tokens > 0, f"max_tokens must be positive, got {self.max_tokens}")


def parse_effort(value: str) -> Effort:
    """Check an effort level from the environment.

    Raises:
        AgentConfigError: If `value` is not a known effort level.
    """
    match value:
        case "low" | "medium" | "high" | "xhigh" | "max":
            return value
        case _:
            raise AgentConfigError(
                f"AGENT_EFFORT must be low, medium, high, xhigh or max (got {value!r})."
            )


def settings_from_env() -> ClaudeSettings:
    """Read ANTHROPIC_MODEL and AGENT_EFFORT, falling back to the defaults."""
    model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    effort = parse_effort(os.environ.get("AGENT_EFFORT", "").strip() or "medium")
    return ClaudeSettings(model=model, effort=effort)


class ClaudeClient:
    """An `LLMClient` that calls the Anthropic Messages API."""

    def __init__(self, sdk: anthropic.Anthropic, settings: ClaudeSettings) -> None:
        self._sdk = sdk
        self._settings = settings

    def create_message(
        self, system: str, messages: list[BetaMessageParam], tools: list[BetaToolParam]
    ) -> BetaMessage:
        """Send one request with this app's settings and return the reply.

        Raises:
            LLMError: With a short, user-friendly message if the request fails.
        """
        try:
            reply = self._sdk.beta.messages.create(
                model=self._settings.model,
                max_tokens=self._settings.max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                # Adaptive thinking: Claude decides how much to reason. "summarized"
                # gives us a readable summary of that reasoning to show the user.
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": self._settings.effort},
                # Caches the system prompt, tools and earlier turns between loop
                # steps, so each step re-reads them at a fraction of the price.
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Invalid or missing ANTHROPIC_API_KEY.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Rate limited by the Claude API. Try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Claude API.") from exc
        return reply


def has_api_key() -> bool:
    """True if an API key (or auth token) is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def claude_client_from_env() -> ClaudeClient:
    """Build the real client from environment variables.

    Raises:
        AgentConfigError: If no API key is set or a setting is invalid.
    """
    if not has_api_key():
        raise AgentConfigError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or to the .env file."
        )
    settings = settings_from_env()
    return ClaudeClient(anthropic.Anthropic(timeout=REQUEST_TIMEOUT_S), settings)
