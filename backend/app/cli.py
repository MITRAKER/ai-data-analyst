"""Ask the agent a question from the terminal and watch every step.

    uv run python -m app.cli ../data/sample_sales.csv "Which region's revenue fell the most in Q4?"

Needs ANTHROPIC_API_KEY in your environment (or in the .env file).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from app.agent.events import AgentEvent, ToolCallEvent
from app.agent.llm import AgentConfigError, LLMClient, claude_client_from_env
from app.agent.orchestrator import DataAnalystAgent
from app.config import load_dotenv
from app.datastore import MAX_UPLOAD_BYTES, DatasetError, DataStore
from app.files import read_capped

DIM: Final = "\033[2m"
BOLD: Final = "\033[1m"
RED: Final = "\033[31m"
GREEN: Final = "\033[32m"
CYAN: Final = "\033[36m"
RESET: Final = "\033[0m"
PREVIEW_CHARS: Final = 500
THINKING_CHARS: Final = 400


def build_parser() -> argparse.ArgumentParser:
    """The command-line arguments: one or more CSV files, then the question."""
    parser = argparse.ArgumentParser(prog="ai-analyst", description="AI Data Analyst (terminal)")
    _ = parser.add_argument("items", nargs="+", metavar="CSV... QUESTION")
    return parser


def load_files(store: DataStore, paths: Sequence[str]) -> None:
    """Load each CSV file into the store.

    Raises:
        DatasetError: If a file is missing, too big or not valid CSV.
    """
    for name in paths:
        path = Path(name)
        if not path.is_file():
            raise DatasetError(f"{name}: no such file.")
        content = read_capped(path, MAX_UPLOAD_BYTES)
        if content is None:
            raise DatasetError(f"{name}: larger than {MAX_UPLOAD_BYTES // 2**20} MB.")
        info = store.load_csv(path.name, content)
        print(f"{DIM}Loaded {name} as table `{info['name']}` ({info['row_count']:,} rows){RESET}")


def render(event: AgentEvent) -> str:
    """One event as colored text for the terminal."""
    if event["type"] == "thinking":
        return f"{DIM}💭 {event['text'].strip()[:THINKING_CHARS]}{RESET}\n"
    if event["type"] == "note":
        return f"{DIM}{event['text'].strip()}{RESET}\n"
    if event["type"] == "tool_call":
        return render_tool_call(event)
    if event["type"] == "tool_result":
        color = RED if event["is_error"] else GREEN
        content = event["content"]
        preview = content if len(content) <= PREVIEW_CHARS else content[:PREVIEW_CHARS] + "…"
        return f"{color}  ↳ {preview}{RESET}\n"
    if event["type"] == "answer":
        return f"{BOLD}Answer{RESET} ({event['steps']} steps):\n{event['text']}"
    return f"{RED}Error: {event['message']}{RESET}"


def render_tool_call(event: ToolCallEvent) -> str:
    """A tool call with its purpose and the SQL or code it runs."""
    inputs = event["input"]
    label = inputs.get("purpose") or inputs.get("title") or ""
    lines = [f"{CYAN}▶ {event['name']}{RESET}: {label}"]
    for key in ("sql", "code"):
        value = inputs.get(key)
        if isinstance(value, str):
            lines.append(f"{DIM}  " + value.replace("\n", "\n  ") + RESET)
    return "\n".join(lines)


def save_charts(event: AgentEvent, folder: Path) -> list[Path]:
    """Write each chart of an answer to chart_N.json (Plotly JSON)."""
    if event["type"] != "answer":
        return []
    saved = []
    for number, chart in enumerate(event["charts"], 1):
        path = folder / f"chart_{number}.json"
        _ = path.write_text(json.dumps(chart), encoding="utf-8")
        saved.append(path)
    return saved


def main(argv: Sequence[str] | None = None, llm: LLMClient | None = None) -> int:
    """Run the CLI. Returns the exit code: 0 for an answer, 1 for an error, 2 for bad usage."""
    parser = build_parser()
    *csv_paths, question = parser.parse_args(argv).items
    if not csv_paths:
        print(f"{RED}Give at least one CSV file before the question.{RESET}")
        return 2
    load_dotenv()
    store = DataStore()
    try:
        load_files(store, csv_paths)
        client = llm if llm is not None else claude_client_from_env()
    except (DatasetError, AgentConfigError) as exc:
        print(f"{RED}{exc}{RESET}")
        return 2
    print(f"\n{BOLD}Q: {question}{RESET}\n")
    exit_code = 1
    for event in DataAnalystAgent(store, client).run(question):
        print(render(event))
        for path in save_charts(event, Path.cwd()):
            print(f"{DIM}Saved chart spec to {path.name} (Plotly JSON){RESET}")
        if event["type"] == "answer":
            exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
