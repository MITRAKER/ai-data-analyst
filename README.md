# AI Data Analyst

[![CI](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/ci.yml)
[![CodeQL](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/codeql.yml)
[![Python 3.12 | 3.13 | 3.14 | 3.15](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14%20%7C%203.15-3776ab)](backend/pyproject.toml)
[![NASA/JPL Power of Ten](https://img.shields.io/badge/NASA%2FJPL-Power%20of%20Ten-0b3d91)](docs/CODING_STANDARD.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Ask questions about your data in plain English. Upload a CSV (or, later, connect a
Postgres database), ask something like *"Which region's revenue dropped the most in Q4?"*,
and an AI agent plans the analysis, writes and runs SQL and Python, draws a chart,
and explains the answer. Every step it takes is shown, so you can check its work.

> 🚧 Being built step by step. See [LEARNING.md](LEARNING.md) for a lesson on each step.

## How it works

```
User question
     │
     ▼
Agent orchestrator (Claude + tool calling) ◄──┐ may re-analyze
     │                                         │
     ├── query_database  (read-only SQL, DuckDB / Postgres)
     ├── run_python      (pandas in a sandbox)
     └── make_chart      (Plotly)
     │
     ▼
Interpret results  ──►  Answer + visualization
```

## Progress

- [x] **Step 1:** FastAPI backend, CSV upload into DuckDB, safe read-only SQL
- [x] **Step 2:** Agent loop with SQL, Python and chart tools
- [x] **Engineering standards:** CI/CD, the NASA/JPL Power of Ten rules, security scanning, releases
- [ ] **Step 3:** Next.js chat UI with live steps and charts
- [ ] **Step 4:** Postgres support, evaluation set, demo

## Run it locally

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and
`make`. [CONTRIBUTING.md](CONTRIBUTING.md#prerequisites) explains how to install
them.

```bash
make setup    # installs the exact package versions from backend/uv.lock
make run      # starts the API on http://localhost:8000
```

Then open http://localhost:8000/docs for the interactive API, or:

```bash
curl -F file=@data/sample_sales.csv localhost:8000/datasets
curl -X POST localhost:8000/query -H 'content-type: application/json' \
  -d '{"sql": "SELECT region, SUM(revenue) FROM sample_sales GROUP BY 1"}'
```

### Ask the agent

Copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY`, then:

```bash
cd backend
uv run python -m app.cli ../data/sample_sales.csv "Which region's revenue fell the most in Q4, and why?"
```

You'll see every step: the SQL it writes, the Python it runs, any errors it
recovers from, and the final answer. Or call `POST /ask` with `{"question": "..."}`.

### Or run it with Docker

```bash
make docker
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY ai-data-analyst
```

`-e ANTHROPIC_API_KEY` with no value copies the key from your shell into the
container, so the key is never stored in the image. Each release also publishes
the image to the GitHub Container Registry, as
`ghcr.io/mitraker/ai-data-analyst`.

## Quality

Every pull request has to pass these checks before it is merged:

- **Ruff** for lint and formatting, including the Bandit security rules
- **mypy** (strict) and **basedpyright**, two independent type checkers
- **The NASA/JPL "Power of Ten" rules**, adapted to Python and enforced by
  [our own checker](backend/tools/power_of_ten.py): no recursion, bounded loops
  and memory, short functions, runtime checks instead of `assert`, and more. See
  [docs/CODING_STANDARD.md](docs/CODING_STANDARD.md)
- **pytest** on Python 3.12, 3.13, 3.14 and 3.15, with warnings as errors and at
  least 95% branch coverage. The tests use a fake Claude client, so they need no
  API key and cost nothing
- **pip-audit** for known vulnerabilities in the locked dependencies
- **pre-commit** hooks: secrets, file hygiene, ShellCheck, and zizmor for the
  GitHub Actions workflows
- **Docker**: the image is built, started and smoke-tested
- **CodeQL** security analysis of the Python code and the workflows

`make check` runs the code checks on your computer. [CONTRIBUTING.md](CONTRIBUTING.md)
explains the workflow, and [SECURITY.md](SECURITY.md) explains how the app keeps
AI-written SQL and Python in check and how to report a vulnerability.

## Tech stack

Python · FastAPI · DuckDB · pandas · Claude API (tool use) · uv · Ruff · mypy ·
pytest · Docker · GitHub Actions · Next.js (step 3)
