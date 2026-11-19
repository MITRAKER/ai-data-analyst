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

## Lesson 2: The agent loop (Claude + tool calling)

### What we built

| File | Job |
|---|---|
| `backend/app/agent/orchestrator.py` | **The agent loop**: talks to Claude, runs tools, repeats until there's an answer |
| `backend/app/agent/tools.py` | The 3 tools: `query_database`, `run_python`, `make_chart` |
| `backend/app/agent/sandbox.py` | Runs AI-written Python safely |
| `backend/app/cli.py` | Ask questions from the terminal and watch every step |
| `POST /ask` in `main.py` | The same agent behind the API |
| `backend/tests/test_agent.py` | 22 new tests that use a **fake** Claude |

### The big idea: an agent is just a loop

People talk about "agents" as if they're magic. Here's the whole thing:

```
messages = [user's question]
loop (at most 12 times):
    reply = Claude(system prompt + schema, tool definitions, messages)
    if reply.stop_reason == "tool_use":       # Claude wants to use tools
        for each tool call in reply:
            result = OUR CODE runs the tool
        messages += [reply, all the results]  # Claude sees what happened
    else:                                      # "end_turn"
        return reply.text                      # the final answer
```

Open `orchestrator.py` and find `def run`. It's about 80 lines, and that's the
entire agent from the diagram in the screenshot:

| Diagram box | Code |
|---|---|
| Agent orchestrator, "plans analysis steps" | Claude, guided by `SYSTEM_PROMPT` |
| Query database / Run code / Generate chart | `TOOL_DEFINITIONS` + `ToolExecutor` |
| "may re-analyze" | the loop: errors go back to Claude, and it tries again |
| Interpret results, Answer + visualization | Claude's final message + the `charts` list |

### How tool calling actually works

1. **We describe tools to Claude** with a name, a description and a JSON Schema
   (see `TOOL_DEFINITIONS`). Claude never runs anything itself.
2. **Claude replies with a request**, a `tool_use` block like
   `{"name": "query_database", "input": {"sql": "SELECT ...", "purpose": "..."}}`,
   and `stop_reason == "tool_use"`.
3. **We run it** and send back a `tool_result` block with the same `tool_use_id`,
   so Claude knows which result belongs to which request.
4. **Claude reads the result** and decides what to do next: another query, a chart,
   or the final answer.

Two rules from the API that are easy to get wrong (both are tested):
- Send Claude's whole reply back unchanged (`response.content`), including its
  thinking blocks. Don't send just the text.
- If Claude asks for several tools at once, return **all** the results in **one**
  user message.

### Design decisions, and why

**Tool descriptions are prompts.** Look at how much `query_database`'s
description says: *one* SELECT, prefer aggregating, and what to do on error.
Claude chooses tools based on these words, so vague descriptions lead to bad tool
use. `strict: true` makes Claude's inputs always match the schema exactly.

**Every tool has a `purpose` field.** It costs nothing, and it gives the user a
plain-English line for each step ("Revenue by region"). It also makes Claude
state its intent before acting, which tends to improve its choices.

**Errors are information, not crashes.** A typo in SQL returns the database's
error with `is_error: true`. Claude reads *column "revenu" not found* and fixes
it. That's the "may re-analyze" arrow. Only truly unexpected errors stop the loop.

**The schema goes in the system prompt.** `build_schema_context()` uses the same
`describe()` from Lesson 1, so Claude knows the column names before it writes
any SQL. Otherwise its first step would always be guessing.

**Code gets data through SQL, not files.** `run_python` takes a `sql` query and a
`code` string. We run the SQL through the same safety guard, hand the result to
the code as `df`, and return only what the code prints. The AI never touches files.

**Charts are data, not images.** `make_chart` returns a Plotly JSON spec
(`{data, layout}`) that the browser will draw in step 3. It's interactive, small,
and needs no extra Python package.

**Caps everywhere:** 12 steps per question, 100 rows shown to Claude, 15 seconds
per code run. An agent without limits can loop forever and run up a bill.

### Running AI-written code safely (`sandbox.py`)

Same idea as Lesson 1, defense in depth:
1. **Inspect before running.** `check_code()` parses the code into a syntax tree
   (`ast`) and blocks `import os`, `open(...)`, `eval`, `__import__`, dunder
   tricks like `().__class__`, and pandas file methods like `to_csv`.
2. **Separate process.** It runs in a new `python -I` process, so a crash can't
   take down the server.
3. **Limits.** A 15-second timeout, a 10-second CPU cap and a 1 GB memory cap.
4. **No secrets.** The child process gets an empty folder and almost no
   environment variables, so your API key isn't visible to it.

Be honest about the limits in interviews: this is good for a portfolio project.
For a real product, you'd add a container with no network access (Docker or
gVisor), or use a hosted code-execution service.

### Claude API settings we chose (`_call_claude`)

| Setting | Why |
|---|---|
| `model="claude-opus-5-5"` | The current default Claude model. Change it with `ANTHROPIC_MODEL` |
| `thinking={"type": "adaptive", "display": "summarized"}` | Claude decides how much to reason, and we get a readable summary to show the user |
| `output_config={"effort": "medium"}` | Balances quality and cost. Try `high` for harder questions (`AGENT_EFFORT`) |
| `cache_control={"type": "ephemeral"}` | Every loop step re-sends the same system prompt and history. Caching makes those repeats much cheaper |
| `fallbacks="default"` | If the model declines a request, the API retries on a fallback model |

We also handle every way the loop can end: `end_turn` (answer), `tool_use`
(keep going), `max_tokens` (answer cut off), `refusal`, `pause_turn`, and API
errors like a bad key or rate limits.

**Why write the loop ourselves?** Anthropic's SDK has a "tool runner" that does
the loop for you, and there's also **Claude Managed Agents**, where Anthropic
hosts the whole loop and a code sandbox. Both are great for production. We wrote
the loop by hand because (a) understanding it is the point of this project, and
(b) we want to `yield` every step to stream it to the UI in step 3. In an
interview, being able to explain this loop line by line is the skill.

### Testing an AI app without paying for AI

`test_agent.py` uses a `FakeClient` that returns **scripted** Claude replies.
That tests *our* code (tools run, results go back in the right shape, errors are
recoverable, the loop stops) for free, in milliseconds, with the same result
every run. Testing the *quality* of Claude's answers is different. That's the
evaluation set in step 4.

### Try it

```bash
cp .env.example .env            # then paste your key after ANTHROPIC_API_KEY=
cd backend
pip install -r requirements-dev.txt
python -m pytest -q             # 38 passed, no key needed
python -m app.cli ../data/sample_sales.csv "Which region's revenue fell the most in Q4, and why?"
```

Watch the steps. Does it find the South region's Q4 drop? Does it dig into *why*
(which products or channels)?

### Exercises

1. **Add a tool.** Write `describe_column` that returns min, max, mean, the number
   of distinct values and the top 5 values for one column. Add the definition and
   the handler, then a test with `FakeClient`. Does Claude use it?
2. **Break it on purpose.** Ask *"Delete all the South orders"*. What does Claude
   do? Which layer would stop it if it tried?
3. **Prompt engineering.** Remove the "Check your numbers" line from
   `SYSTEM_PROMPT`, ask the same question 3 times, then put it back. Do you see a
   difference? (This is why we build an evaluation set in step 4.)
4. **Cost awareness.** Print `response.usage` in `_call_claude`. How many tokens
   does one question use? How much is read from the cache on later steps
   (`cache_read_input_tokens`)?

### Words to know

- **Tool use / function calling:** the model asks *your code* to run a function and reads the result.
- **Agent loop:** call model, run tools, repeat until the model answers.
- **`stop_reason`:** why the model stopped (`tool_use`, `end_turn`, `max_tokens`, `refusal`).
- **System prompt:** standing instructions and context, separate from the user's question.
- **AST (abstract syntax tree):** code parsed into a structure you can inspect safely.
- **Prompt caching:** reusing an already-processed prompt prefix so it costs less.
- **Test double / fake:** a stand-in object (our `FakeClient`) that makes tests fast and predictable.

---

*Next: Lesson 3, the chat UI. Streaming agent steps to the browser live with
Server-Sent Events, and drawing the charts with Plotly.*
