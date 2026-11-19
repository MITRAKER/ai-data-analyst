# Learning guide: how this project was built

This file grows with each step. Each lesson covers **what** was built, **why** it
was designed that way, the **key ideas** behind it, and an **exercise** so you can
practice on your own.

---

## Lesson 1: The data backend (FastAPI + DuckDB)

### What we built

Before an AI can analyze data, the data needs a home and a safe way to query it.
Step 1 is that foundation, with no AI yet:

| File | Job |
|---|---|
| `backend/app/main.py` | The web API: upload a CSV, list datasets, see a schema, run SQL |
| `backend/app/datastore.py` | Loads CSVs into DuckDB, describes tables, runs queries |
| `backend/app/sql_guard.py` | Makes sure only read-only SQL can run |
| `backend/tests/test_api.py` | 16 automated tests |
| `data/sample_sales.csv` | 2,000 made-up sales orders to play with |
| `.github/workflows/ci.yml` | Runs the tests on GitHub on every push |

The flow looks like this:

```
CSV upload ──► pandas reads it ──► columns cleaned ──► DuckDB table
                                                          │
SQL from you (later: from the AI) ──► sql_guard ──► DuckDB ──► rows as JSON
```

### Why these choices

**Why build the backend before the AI?** An agent is only as good as its tools.
In step 2, Claude won't touch the database directly. It will *ask* our code to
run a query, and our code decides whether that's allowed. So we build and test the
tools first, by hand, with no AI involved.

**Why DuckDB?** It's an *analytical* database that runs inside Python. There is
no server to install. It's very fast at the queries analysts write (`GROUP BY`,
`SUM`, `date_trunc`), and it speaks normal SQL, so the AI's SQL skills transfer.
A comparison:

- **SQLite** is also embedded, but it's built for app data (many small reads and
  writes), not analytics.
- **Postgres** is great, but it needs a server. We'll add it in step 4 as a
  "connect your own database" option.

**Why FastAPI?** It's the most common modern Python web framework. You describe
your inputs with type hints, and FastAPI validates them and generates interactive
docs at `/docs` for free.

### Key ideas

**1. Never trust SQL you didn't write.** In step 2 an LLM writes SQL. LLMs make
mistakes, and a malicious CSV could even contain text that tricks the model. So
we have **three layers of defense**. This idea is called *defense in depth*:

1. **Parse, don't pattern-match.** `sql_guard.py` asks DuckDB's own parser what
   each statement is. A naive check like `sql.startswith("select")` would let
   `SELECT 1; DROP TABLE sales` through. The parser sees two statements and we
   reject it.
2. **Lock the database down.** We open DuckDB with `enable_external_access=False`,
   so even a valid `SELECT * FROM read_csv('/etc/passwd')` can't read files.
   `lock_configuration=True` stops SQL from turning that setting back on.
3. **Cap the output.** Queries are wrapped as `SELECT * FROM (...) LIMIT n+1`. We
   fetch one extra row so we can tell the caller the result was truncated. That
   matters later, because the AI needs to know when it's seeing only part of the
   data.

**2. Error messages are for the agent too.** When SQL fails, we return DuckDB's
real message (for example, *column "no_such_column" not found*). In step 2 the
agent will read that error and fix its own query. That's the "may re-analyze"
loop in the diagram.

**3. `describe()` is the AI's map.** The schema, row count and 5 sample rows are
exactly what we'll put in front of Claude so it knows the column names and types
before it writes any SQL. Without that, it would guess column names.

**4. Clean the data at the door.** CSV headers like `Total $` or `Order ID` are
painful in SQL. We convert them to `total` and `order_id`, rename duplicate
columns, and turn text like `2025-03-14` into real dates so that date functions
work.

**5. The app factory pattern.** `create_app(store)` builds the app with whatever
datastore you hand it. The tests pass a fresh in-memory database each time, so no
test can affect another. This is a small form of *dependency injection*.

### Try it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q             # should print "16 passed"
uvicorn app.main:app --reload   # then open http://localhost:8000/docs
```

In `/docs`, upload `data/sample_sales.csv` with **POST /datasets**, then try
**POST /query** with:

```sql
SELECT region, date_trunc('quarter', order_date) AS quarter, ROUND(SUM(revenue)) AS revenue
FROM sample_sales GROUP BY 1, 2 ORDER BY 1, 2
```

Look at the South region. Something happens in Q4. Spotting things like that is
what our agent will learn to do on its own.

### Exercises

1. **Break the guard.** Try to get a harmful query past `/query`. Ideas: `PRAGMA`,
   `CREATE TABLE`, a comment trick like `SELECT 1 -- ; DROP TABLE x`. Which layer
   stops each one?
2. **Add an endpoint.** Write `DELETE /datasets/{name}` that drops a table, and add
   a test for it. Hint: `run_query` can't do this, because it only allows SELECT.
   Why is it fine for *this* endpoint to run a `DROP`?
3. **Column stats.** Add a `stats` field to `describe()` with min, max and the
   number of missing values for each column. This will give the agent more context
   later.

### Words to know

- **Embedded database:** a database that runs inside your program, not as a separate server.
- **Defense in depth:** several independent safety layers, so one failure isn't fatal.
- **Pydantic model:** a Python class that validates incoming JSON (`QueryRequest`).
- **CI (continuous integration):** GitHub runs your tests automatically on every change.

---

*Next: Lesson 2, the agent loop. How Claude decides which tool to call, how tool
results flow back into the conversation, and how to run AI-written Python safely.*
