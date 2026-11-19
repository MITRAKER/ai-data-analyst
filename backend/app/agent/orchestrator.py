"""The agent orchestrator: the loop that turns a question into an answer.

This is the heart of the project. The whole "agent" is this loop:

    messages = [question]
    repeat:
        response = Claude(system prompt, tools, messages)
        if Claude asked to use tools:
            run each tool, append the results to messages, loop again
        else:
            Claude has written the final answer -> stop

Claude decides *which* tool to call and *what* to pass. Our code decides
*whether* that is allowed and actually runs it. We also cap the number of steps
so a confused agent can't loop forever (and spend money forever).

`run()` is a generator: it `yield`s an event for every step (tool call, tool
result, final answer). The CLI prints these events, and in step 3 the web UI
will stream them live.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import anthropic

from ..datastore import DataStore
from .tools import TOOL_DEFINITIONS, ToolExecutor

DEFAULT_MODEL = "claude-opus-5-5"
MAX_STEPS = 12

SYSTEM_PROMPT = """You are an expert data analyst. You answer questions about the user's \
datasets by querying and analyzing the data with your tools, never by guessing.

How to work:
- Look at the schema below before writing SQL. Use only the tables and columns that exist.
- Start with a query that answers the question directly, then dig deeper if the result \
raises an obvious follow-up (for example, which segment explains a drop).
- Aggregate in SQL. Use run_python only for things SQL does poorly (statistics, correlations, \
forecasts).
- If a tool returns an error, read it, fix the problem, and try again.
- Check your numbers: if a result looks surprising, verify it with a second query.
- Make one chart when it helps the user see the answer (trends, comparisons). Don't make \
charts that add nothing.

Final answer:
- Lead with the direct answer in one or two sentences, with the key numbers.
- Then up to 4 short bullet points of supporting findings.
- Mention any caveat that matters (missing data, small samples, truncated results).
- Don't repeat SQL or code in the answer; the user can see your steps separately.

The SQL dialect is DuckDB. Useful functions: date_trunc('month', col), strftime(col, '%Y-%m'), \
quantile_cont(col, 0.5), corr(a, b).
"""


def build_schema_context(store: DataStore, tables: list[str]) -> str:
    """Describe the datasets for Claude: columns, types, row count and sample rows."""
    parts = []
    for table in tables:
        info = store.describe(table, sample_rows=3)
        cols = ", ".join(f"{c['name']} ({c['type']})" for c in info["columns"])
        sample = "\n".join(f"    {row}" for row in info["sample"])
        parts.append(
            f"Table `{table}` ({info['row_count']:,} rows)\n  Columns: {cols}\n  Sample rows:\n{sample}"
        )
    return "Available datasets:\n\n" + "\n\n".join(parts)


class DataAnalystAgent:
    def __init__(
        self,
        store: DataStore,
        client: Any | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self.store = store
        self.tools = ToolExecutor(store)
        # The client is injectable so tests can pass a fake one (no API key, no cost).
        if client is None and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to backend/.env or your environment.")
        self.client = client or anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.getenv("AGENT_EFFORT", "medium")
        self.max_steps = max_steps

    def _call_claude(self, system: str, messages: list[dict[str, Any]]) -> Any:
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
            # Adaptive thinking: Claude decides how much to reason. "summarized"
            # gives us a readable summary of that reasoning to show the user.
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            # Caches the system prompt + tools + earlier turns between loop
            # iterations, so each step re-reads them at a fraction of the price.
            cache_control={"type": "ephemeral"},
            # If the model declines a request, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def run(self, question: str, tables: list[str] | None = None) -> Iterator[dict[str, Any]]:
        tables = tables or self.store.list_tables()
        if not tables:
            yield {"type": "error", "message": "No datasets uploaded yet. Upload a CSV first."}
            return

        system = SYSTEM_PROMPT + "\n\n" + build_schema_context(self.store, tables)
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        charts: list[dict[str, Any]] = []

        for step in range(1, self.max_steps + 1):
            try:
                response = self._call_claude(system, messages)
            except anthropic.AuthenticationError:
                yield {"type": "error", "message": "Invalid or missing ANTHROPIC_API_KEY."}
                return
            except anthropic.RateLimitError:
                yield {"type": "error", "message": "Rate limited by the Claude API. Try again shortly."}
                return
            except anthropic.APIStatusError as exc:
                yield {"type": "error", "message": f"Claude API error ({exc.status_code}): {exc.message}"}
                return
            except anthropic.APIConnectionError:
                yield {"type": "error", "message": "Could not reach the Claude API."}
                return

            # Always append Claude's full reply (including thinking and tool_use
            # blocks): the API needs them, unchanged, on the next request.
            messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "thinking" and getattr(block, "thinking", ""):
                    yield {"type": "thinking", "text": block.thinking}
                elif block.type == "text" and response.stop_reason == "tool_use" and block.text.strip():
                    yield {"type": "note", "text": block.text}

            if response.stop_reason == "refusal":
                yield {"type": "error", "message": "The model declined to answer this request."}
                return
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                # end_turn (or max_tokens): the text is the final answer.
                answer = "".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    answer += "\n\n(The answer was cut off because it hit the length limit.)"
                yield {"type": "answer", "text": answer, "charts": charts, "steps": step}
                return

            # Claude asked for one or more tools. Run them all, then send every
            # result back in ONE user message (that's what the API expects).
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                yield {"type": "tool_call", "id": block.id, "name": block.name, "input": block.input}
                outcome = self.tools.execute(block.name, block.input)
                if outcome.chart:
                    charts.append(outcome.chart)
                yield {
                    "type": "tool_result",
                    "id": block.id,
                    "name": block.name,
                    "is_error": outcome.is_error,
                    "content": outcome.content,
                    "display": outcome.display,
                    "chart": outcome.chart,
                }
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": outcome.content,
                        "is_error": outcome.is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        yield {
            "type": "error",
            "message": f"Stopped after {self.max_steps} steps without a final answer.",
            "charts": charts,
        }
