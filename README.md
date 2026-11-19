# AI Data Analyst

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
- [ ] **Step 3:** Next.js chat UI with live steps and charts
- [ ] **Step 4:** Postgres support, evaluation set, demo

## Run it locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs for the interactive API, or:

```bash
curl -F file=@../data/sample_sales.csv localhost:8000/datasets
curl -X POST localhost:8000/query -H 'content-type: application/json' \
  -d '{"sql": "SELECT region, SUM(revenue) FROM sample_sales GROUP BY 1"}'
```

### Ask the agent (step 2)

Copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY`, then:

```bash
cd backend
python -m app.cli ../data/sample_sales.csv "Which region's revenue fell the most in Q4, and why?"
```

You'll see every step: the SQL it writes, the Python it runs, any errors it
recovers from, and the final answer. Or call `POST /ask` with `{"question": "..."}`.

Run the tests with `python -m pytest` (they use a fake Claude client, so no API key or cost).

## Tech stack

Python · FastAPI · DuckDB · pandas · Claude API (tool use) · Next.js · Docker · GitHub Actions
