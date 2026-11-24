# AI Data Analyst

[![CI](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/ci.yml)
[![CodeQL](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/MITRAKER/ai-data-analyst/actions/workflows/codeql.yml)
[![Python 3.12 | 3.13 | 3.14 | 3.15](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14%20%7C%203.15-3776ab)](backend/pyproject.toml)
[![Node.js 26](https://img.shields.io/badge/node.js-26-5fa04e)](frontend/.nvmrc)
[![NASA/JPL Power of Ten](https://img.shields.io/badge/NASA%2FJPL-Power%20of%20Ten-0b3d91)](docs/CODING_STANDARD.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Ask questions about your data in plain English. Upload a CSV (or, later, connect a
Postgres database), ask something like *"Which region's revenue dropped the most in Q4?"*,
and an AI agent plans the analysis, writes and runs SQL and Python, draws a chart,
and explains the answer. Every step it takes is shown, so you can check its work.

> 🚧 Being built step by step. See [LEARNING.md](LEARNING.md) for a lesson on each step.

## How it works

```
Web UI (Next.js) ──── your question ────► API (FastAPI)
     ▲                                         │
     │                                         ▼
     │                Agent orchestrator (Claude + tool calling) ◄──┐ may re-analyze
     │                                         │                    │
     │                                         ├── query_database  (read-only SQL, DuckDB / Postgres)
     │                                         ├── run_python      (pandas in a sandbox)
     │                                         └── make_chart      (Plotly)
     │                                         │
     └──── every step, live ◄──────────────────┘
           (Server-Sent Events), then the answer and its charts
```

The web page shows every step while the agent works: its plan, the SQL and
Python it writes, and the results. You can check its work, or press Stop.

## Progress

- [x] **Step 1:** FastAPI backend, CSV upload into DuckDB, safe read-only SQL
- [x] **Step 2:** Agent loop with SQL, Python and chart tools
- [x] **Engineering standards:** CI/CD, the NASA/JPL Power of Ten rules, security scanning, releases
- [x] **Step 3:** Next.js chat UI with live steps and charts, and Docker Compose
- [ ] **Step 4:** Postgres support, evaluation set, demo

## Run it with Docker Compose

The quickest way to try the whole app. You need
[Docker](https://docs.docker.com/get-started/get-docker/).

```bash
cp .env.example .env        # then add your ANTHROPIC_API_KEY to .env
docker compose up --build   # or: make up
```

Open http://localhost:3000, upload `data/sample_sales.csv`, and click one of the
suggested questions. Without a key the app still runs, and the page tells you
that the agent can't answer yet. Your data is kept in a Docker volume between
restarts; `docker compose down --volumes` deletes it.

The web UI answers only to this computer's own names: `localhost`, `127.0.0.1`
and `[::1]`. To open it under another name that points to this computer, add
that name to `ALLOWED_HOSTS` in `.env` ([SECURITY.md](SECURITY.md#the-web-ui)
explains why).

## Run it locally

For development you need [uv](https://docs.astral.sh/uv/getting-started/installation/),
`make`, and [Node.js](https://nodejs.org/) 26 for the web UI.
[CONTRIBUTING.md](CONTRIBUTING.md#prerequisites) explains how to install them.

```bash
make setup      # installs the exact package versions from backend/uv.lock
make run        # starts the API on http://localhost:8000
```

To use the web UI, in a second terminal:

```bash
make web-setup  # once: installs the exact versions from frontend/package-lock.json
make web-dev    # starts the web UI on http://localhost:3000
```

Or use the API directly: open http://localhost:8000/docs for the interactive API, or:

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
recovers from, and the final answer. Or call `POST /ask` with `{"question": "..."}`,
or `POST /ask/stream` to get each step as it happens.

### Only the API, with Docker

```bash
make docker
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY ai-data-analyst
```

`-e ANTHROPIC_API_KEY` with no value copies the key from your shell into the
container, so the key is never stored in the image. Each release also publishes
the API's image to the GitHub Container Registry, as
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
- **The web UI**: Prettier, ESLint with the Power of Ten rules for TypeScript,
  strict TypeScript, and Vitest with at least 95% coverage; `npm audit` and
  npm's registry signatures; a production build
- **Playwright** browser tests on a desktop and a phone screen, with **axe**
  accessibility checks, against a stand-in for the API, so they need no key
- **Docker Compose**: both images together, with their security settings
- **CodeQL** security analysis of the Python and TypeScript code and the
  workflows

`make check` runs the backend checks on your computer, and `make web-check` the
web UI's. [CONTRIBUTING.md](CONTRIBUTING.md)
explains the workflow, and [SECURITY.md](SECURITY.md) explains how the app keeps
AI-written SQL and Python in check and how to report a vulnerability.

## Tech stack

Python · FastAPI · DuckDB · pandas · Claude API (tool use) · uv · Ruff · mypy ·
pytest · TypeScript · Next.js · React · Plotly · Vitest · Playwright · Docker
Compose · GitHub Actions
