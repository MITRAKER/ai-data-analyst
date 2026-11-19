"""Ask the agent a question from the terminal and watch every step.

    python -m app.cli ../data/sample_sales.csv "Which region's revenue fell the most in Q4?"

Needs ANTHROPIC_API_KEY in your environment (or in backend/.env).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent.orchestrator import DataAnalystAgent
from .config import load_dotenv
from .datastore import DataStore

DIM, BOLD, RED, GREEN, CYAN, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[36m", "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Data Analyst (terminal)")
    parser.add_argument("csv", nargs="+", help="One or more CSV files, then your question")
    args = parser.parse_args()
    *csv_paths, question = args.csv
    if not csv_paths:
        parser.error("Give at least one CSV file before the question.")

    load_dotenv()

    store = DataStore()
    for p in csv_paths:
        info = store.load_csv(Path(p).name, Path(p).read_bytes())
        print(f"{DIM}Loaded {p} as table `{info['name']}` ({info['row_count']:,} rows){RESET}")

    try:
        agent = DataAnalystAgent(store)
    except RuntimeError as exc:
        raise SystemExit(f"{RED}{exc}{RESET}") from None
    print(f"\n{BOLD}Q: {question}{RESET}\n")
    for event in agent.run(question):
        kind = event["type"]
        if kind == "thinking":
            print(f"{DIM}💭 {event['text'].strip()[:400]}{RESET}\n")
        elif kind == "note":
            print(f"{DIM}{event['text'].strip()}{RESET}\n")
        elif kind == "tool_call":
            inp = event["input"]
            print(f"{CYAN}▶ {event['name']}{RESET}: {inp.get('purpose') or inp.get('title', '')}")
            if "sql" in inp:
                print(f"{DIM}  {inp['sql']}{RESET}")
            if "code" in inp:
                print(f"{DIM}  " + inp["code"].replace("\n", "\n  ") + RESET)
        elif kind == "tool_result":
            color = RED if event["is_error"] else GREEN
            preview = event["content"] if len(event["content"]) < 500 else event["content"][:500] + "…"
            print(f"{color}  ↳ {preview}{RESET}\n")
        elif kind == "answer":
            print(f"{BOLD}Answer{RESET} ({event['steps']} steps):\n{event['text']}")
            for i, chart in enumerate(event["charts"], 1):
                out = Path(f"chart_{i}.json")
                out.write_text(json.dumps(chart))
                print(f"{DIM}Saved chart spec to {out} (Plotly JSON){RESET}")
        elif kind == "error":
            print(f"{RED}Error: {event['message']}{RESET}")


if __name__ == "__main__":
    main()
