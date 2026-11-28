# Coding standard

This is the coding standard of AI Data Analyst. It adapts NASA/JPL's "Power of
Ten" rules to Python, and then to the TypeScript of the web UI, and says exactly
which tool checks each rule. This file is the source of truth. CONTRIBUTING.md
and LEARNING.md only summarize it.

## Contents

- [Why these rules](#why-these-rules)
- [Where the rules apply](#where-the-rules-apply)
- [How the rules are checked](#how-the-rules-are-checked)
- [The ten rules](#the-ten-rules)
- [The web UI (TypeScript)](#the-web-ui-typescript)
- [Running the checker](#running-the-checker)
- [What the checker cannot see](#what-the-checker-cannot-see)
- [Suppressions](#suppressions)
- [Changing this standard](#changing-this-standard)
- [References](#references)

## Why these rules

In 2006 Gerard Holzmann, of NASA's Jet Propulsion Laboratory (JPL), published
ten rules for safety-critical C code, such as the software that flies
spacecraft. He called them "The Power of Ten". The rules are short on purpose:
few enough to remember, and each one simple enough for a tool to check.

Their goal is code that people can review with confidence and that tools can
analyze completely. This app runs SQL and Python that an AI writes, so it needs
the same things: control flow you can follow, loops that always end, memory use
that stays bounded, and errors that are never silently dropped.

Python is not C, so some rules need a Python version. For example, Python has no
`goto` and no preprocessor, but it has recursion, `while` loops, `eval` and
lambdas. Each rule below gives Holzmann's original idea first, then our Python
version.

## Where the rules apply

| Code | Power of Ten checker | Ruff, mypy, basedpyright |
| --- | --- | --- |
| `backend/app/` (the application) | Yes | Yes |
| `backend/tools/` (the checker itself) | Yes | Yes |
| `backend/tests/` | No | Yes |

The web UI in `frontend/` is TypeScript, so other tools check it: ESLint with
the Power of Ten rules, TypeScript in strict mode, and Prettier. The section
[The web UI (TypeScript)](#the-web-ui-typescript) maps each rule.

The tests are exempt from the Power of Ten checker. pytest is built around
`assert`, test helpers pass functions around, and test data is often a list at
module level. Rules 5, 6 and 9 would forbid all of that. The tests still pass
every other check: lint, formatting, both type checkers, and warnings as errors.

Shell scripts (`scripts/`) are checked by ShellCheck. The GitHub Actions files
(`.github/`) are checked by zizmor and against their JSON schemas. Both run in
pre-commit and in CI.

## How the rules are checked

Every rule is checked by a machine, on every pull request. A human reviewer
still reads the code, but never has to look for these problems by eye.

| Rule | Checked by |
| --- | --- |
| 1. Simple control flow | Power of Ten checker (recursion); Ruff `C901` (complexity at most 10) and Ruff's pylint limits on branches, returns, statements and arguments |
| 2. Loops with a fixed bound | Power of Ten checker |
| 3. Bounded memory | Power of Ten checker (unbounded reads); size limits in the code |
| 4. Short functions | Power of Ten checker (at most 60 lines of code) |
| 5. Assertions | Power of Ten checker (no `assert`, checks without side effects, check density) |
| 6. Smallest scope | Power of Ten checker |
| 7. Check return values | basedpyright `reportUnusedCallResult`; Power of Ten checker (silenced errors); Ruff `BLE`, `S110`, `TRY` |
| 8. Limited metaprogramming | Power of Ten checker |
| 9. Limited indirection | Power of Ten checker |
| 10. Zero warnings | Every tool runs with warnings as errors; Power of Ten checker (suppressions need a reason) |

`make check` runs all of these on your computer. CI runs them on every pull
request, on every push to `main`, and once a week.

## The ten rules

Each rule shows the problems the checker reports, as `R1` to `R10`, and how to
fix them.

### Rule 1: Simple control flow

**Holzmann:** no `goto`, no `setjmp`/`longjmp`, and no recursion, direct or
indirect.

**Our rule:** no function may call itself, either directly or through other
functions. Every function stays simple: Ruff limits its cyclomatic complexity
(the number of paths through it) to 10.

**Why:** with no recursion, the call graph has no cycles. Then a tool, or a
person, can work out the deepest possible chain of calls. A recursive function
can always go one level deeper than you tested, until Python raises
`RecursionError`.

**What the checker does:** it builds a call graph of the checked code and finds
every cycle in it, even across files. It follows plain calls, `self.method()`
and `cls.method()` (including methods that a subclass overrides), `super()`,
calls on objects whose class it can tell from a type annotation or from
`x = SomeClass()`, constructors, and imported names.

```python
# R1: `count_rows` calls itself directly: use a loop with a fixed bound
def count_rows(node: Node) -> int:
    return 1 + sum(count_rows(child) for child in node.children)
```

**How to comply:** rewrite recursion as a loop, keeping a list of the work still
to do, or use a library that walks the structure for you, such as `ast.walk`.
The loop then needs its own bound (rule 2).

### Rule 2: Every loop has a fixed upper bound

**Holzmann:** give every loop a fixed upper bound that a tool can prove.

**Our rule:** use `for` over something of known size: a `range()`, a list, the
rows of a capped result. The checker reports:

- every `while` loop;
- `itertools.count()` and `itertools.cycle()`, and `itertools.repeat(x)`
  without a count, because they never end;
- `iter(callable, sentinel)`, which runs until the sentinel appears, if it ever
  does.

**Why:** a loop that cannot run forever cannot hang the server or spend API
credits forever. The agent loop shows this: it runs at most `MAX_STEPS` (12)
times, whatever the model does.

```python
# R2: `while` loop: loop with `for` over something of fixed size
while not reply.done:
    reply = ask_again(reply)

# Allowed: at most MAX_STEPS rounds
for step in range(1, MAX_STEPS + 1):
    ...
```

**Waiting for other software:** a SQL query or a child process has no loop of
ours to bound. We bound it in time instead, with a watchdog thread
(`backend/app/watchdog.py`) that stops the work when its time limit passes.

### Rule 3: Memory use stays bounded

**Holzmann:** no dynamic memory allocation after initialization.

**Our rule:** Python allocates memory all the time, so we cannot forbid
allocation. Instead, everything that can grow has a fixed upper limit: every
upload, file read, query result, tool result and output buffer. The limits are
named constants, such as `MAX_UPLOAD_BYTES`, `MAX_RESULT_ROWS` and
`MAX_RESULT_CHARS`.

The checker reports reads that have no limit:

- `.read()`, `.readline()` and `.readlines()` without a size;
- `.read_text()`, `.read_bytes()` and `.communicate()`, which always read
  everything;
- `read_csv()`, `read_excel()`, `read_fwf()` and `read_table()` without `nrows=`.

```python
# R3: `.read_text()` reads everything: read at most a fixed amount
text = path.read_text()

# Allowed: read_capped() returns None when the file is too big
content = read_capped(path, MAX_DOTENV_BYTES)
```

**Why:** an upload of a huge file, or a query that returns millions of rows,
should be refused or cut off, not crash the server by running it out of memory.

### Rule 4: Short functions

**Holzmann:** no function longer than what fits on one printed page: about 60
lines.

**Our rule:** at most 60 lines of code per function. The docstring, comments and
blank lines do not count, so explaining code never pushes a function over the
limit.

```text
R4 `run` has 75 lines of code, more than 60: split it
```

**Why:** a function you can see all at once is a function you can understand and
test as a unit. Long functions usually do several jobs; give each job its own
well-named function.

### Rule 5: Assertions

**Holzmann:** use at least two assertions per function on average. Assertions
must have no side effects, and a failed assertion must lead to an explicit
recovery action.

**Our rule:**

- **No `assert` in checked code.** Python removes every `assert` when it runs
  with `python -O`, so the check silently disappears. Call `require(condition,
  message)` from `backend/app/invariants.py` instead. It always runs, and it
  raises `InvariantError` when the condition is false.
- **Checks change nothing.** The arguments of `require()` and `assert_never()`
  must not contain `:=`, `await` or `yield`. The program must behave the same
  whether or not a check runs.
- **Check density of at least 0.5.** Over all checked code, there must be at
  least 0.5 checks per function on average. A check is a `raise` statement, a
  `require()` call or an `assert_never()` call. Functions with no code, such as
  the methods of a `Protocol`, do not count.

```python
# R5: `assert` is removed by `python -O`: call require() instead
assert max_rows > 0

# Allowed
require(max_rows > 0, f"max_rows must be positive, got {max_rows}")
```

**Two kinds of checks.** Bad input from a user or from the AI model is expected:
check it and raise an ordinary error with a helpful message, such as
`DatasetError`, `UnsafeSQLError` or `ToolInputError`. The API and the agent turn
those into messages the user, or the model, can act on. A failed `require()` is
different: it means our own code has a bug. Nothing tries to recover from an
`InvariantError`; it surfaces and gets fixed. That is the "explicit recovery
action" for a broken invariant.

**Why 0.5 and not 2?** In C, an assertion often checks something that Python
checks for you, such as a null pointer or an index out of range. mypy also
checks types before the code ever runs. So we ask for fewer checks than
Holzmann, and count every `raise`. The number is a ratchet: when the code's
density rises, raise `MIN_ASSERTION_DENSITY` in `backend/tools/power_of_ten.py`
to match. Never lower it. When this standard was written, the density was 0.53.

### Rule 6: The smallest possible scope

**Holzmann:** declare data at the smallest possible level of scope.

**Our rule:** no `global` and no `nonlocal`, and no mutable state at module
level or in a class body: no list, dict or set (written out, as a
comprehension, or built with `list()`, `dict()`, `set()`, `bytearray()` or a
`collections` type), and no `+=` outside a function. Module-level constants are
fine when they cannot change: give them a `Final` type and use tuples,
`frozenset`s and strings.

```python
# R6: mutable module or class state: use a constant, or a function
SEEN_TABLES = []

# Allowed
CHART_TYPES: Final = ("bar", "line", "scatter", "pie", "histogram")
```

**Why:** state that any code can change is state that any code can break. Pass
values in as arguments, return results, and keep changing state inside an
object (as `DataStore` does).

### Rule 7: Check every return value

**Holzmann:** check the return value of every function that returns one, and
check the parameters inside every function.

**Our rule:**

- **Never drop a return value.** basedpyright's `reportUnusedCallResult` reports
  every call whose result is not used. When you truly do not need it, discard it
  on purpose with `_ = f()`, so the reader sees it was a choice.
- **Never swallow an error.** In Python, most errors arrive as exceptions. The
  checker reports an `except` block whose body is only `pass` or `...`, and
  `contextlib.suppress(...)`. Ruff also reports a bare `except Exception`
  (`BLE001`) and `try`-`except`-`pass` (`S110`).
- **Check parameters.** See rule 5.

```python
# R7: the error is silently ignored: handle it, or let it propagate
try:
    store.load_csv(name, content)
except DatasetError:
    pass
```

### Rule 8: Limited metaprogramming

**Holzmann:** use the C preprocessor only for header files and simple macros.

**Our rule:** Python has no preprocessor, but it can build and change code while
it runs, which is worse for analysis. The checker reports:

- calls to `eval`, `exec`, `compile`, `__import__`, `getattr`, `setattr`,
  `hasattr`, `delattr`, `globals`, `locals` and `vars`;
- imports of `importlib`, `imp`, `runpy`, `code`, `codeop`, `marshal`, `pickle`,
  `shelve` and `ctypes`;
- metaclasses, and `type(name, bases, namespace)`, which builds a class at run
  time;
- dunder attributes such as `obj.__class__` or `obj.__dict__`. Calls through
  `super()`, such as `super().__init__()`, are allowed.

**Why:** a tool can only check code it can see. `getattr(obj, name)` calls a
method whose name is known only at run time, so no checker can follow it.
`eval` and `pickle` can also run code an attacker wrote. The AI's own Python
runs in a sandbox (`backend/app/agent/sandbox.py`) that blocks the same tricks.

### Rule 9: Limited indirection

**Holzmann:** limit pointers to one level of dereferencing, and do not use
function pointers.

**Our rule:** Python has no pointers, but it has the same idea: a function stored
in a variable and called later. The checker reports:

- every `lambda`;
- a function or method of the checked code used as a value: stored in a
  variable, put in a list, passed as an argument or returned (decorators and
  properties are fine);
- a `Callable` in a type annotation, which means a function is passed around.

```python
# R9: `run_query` is used as a value: call it, or pass an object instead
handler = run_query

# R9: lambda: write a named function, and call it directly
rows.sort(key=lambda row: row[1])
```

**How to comply:** call functions directly, for example with `match` on the tool
name. When code needs to swap behavior, pass an object that implements a
`Protocol`. The agent works this way: it takes any `LLMClient`, so tests pass a
scripted fake instead of the real Claude client. Library functions passed to the
library that expects them, such as `key=str.lower`, are not reported, because
the checker only tracks functions of our own code.

### Rule 10: Zero warnings

**Holzmann:** compile with every warning turned on, fix every warning, and run a
static analyzer every day.

**Our rule:** every tool runs in its strictest useful mode, and a warning fails
the check just like an error:

- **Ruff** with more than 40 rule families, including the Bandit security rules;
- **mypy** in `strict` mode, plus extra error codes;
- **basedpyright** as a second, independent type checker;
- **pytest** with `filterwarnings = ["error"]`, so a `DeprecationWarning` fails
  the test run, and branch coverage of at least 95%;
- **the Power of Ten checker**, which also checks every suppression (below);
- **CodeQL**, GitHub's security analyzer, on every pull request and once a week.

The "every day" part is CI: it runs on every pull request and every push to
`main`, and once a week on a schedule, so a new vulnerability or a new tool
warning shows up even when nobody pushes.

## The web UI (TypeScript)

The web UI follows the same ten rules. TypeScript is not Python, so a few rules
take a different form, and ESLint (`frontend/eslint.config.mjs`) checks them
instead of our own checker. ESLint runs with `--max-warnings=0`, so a warning
fails the check like an error.

| # | In the web UI | Checked by |
| --- | --- | --- |
| 1 | Complexity at most 10, nesting at most 3 levels, no labels | ESLint `complexity`, `max-depth`, `max-nested-callbacks`, `no-labels` |
| 2 | No `while`, `do...while`, `for (;;)` or `for...in`. Loop with `for...of` over something of fixed size, or count up to a limit | ESLint `no-restricted-syntax`, `no-constant-condition` |
| 3 | Every buffer and list has a size cap (`MAX_EVENT_CHARS`, `MAX_STREAM_BYTES`, `MAX_TURNS`, `MAX_TABLE_ROWS` and more), and a request body is checked against its `Content-Length` before it is read | Code review and tests |
| 4 | At most 60 lines per function (blank lines and comments do not count), at most 4 parameters | ESLint `max-lines-per-function`, `max-params` |
| 5 | Every value from outside (network, JSON) is checked by code before it is used. No casts with `as`: a cast only silences the type checker | `events.ts` and `api.ts`; ESLint `consistent-type-assertions` |
| 6 | `const` by default, no `var`, no shadowed names, no mutable state at module level | ESLint `prefer-const`, `no-var`, `no-shadow`; code review for module state |
| 7 | Every promise is awaited, or explicitly dropped with `void`. No empty `catch` blocks | typescript-eslint `no-floating-promises`, `no-misused-promises`; ESLint `no-empty` |
| 8 | No `eval`, `new Function()`, `javascript:` URLs or HTML strings (`dangerouslySetInnerHTML`) | ESLint `no-eval`, `no-new-func`, `no-script-url`, `react/no-danger` |
| 9 | See below: callbacks are allowed, `any` is not | typescript-eslint `strictTypeChecked` |
| 10 | Zero warnings: strict TypeScript (`strict`, `noUncheckedIndexedAccess` and more), typescript-eslint's strictest rule sets, and CodeQL | `npm run check`, CI |

Two rules differ on purpose:

- **Rule 5 has no `require()`.** In Python, `require()` checks invariants that
  the type checker can't see. In the web UI, most such checks are about data
  from outside, and TypeScript's types vanish at run time. So the code checks
  that data with type guards and parsers (`isObject`, `parseAgentEvent`), which
  also tell the type checker what they proved. There is no density count.
- **Rule 9 allows callbacks.** React is built on functions passed as values:
  `onClick`, `useEffect` and every `.map()` over a list. Banning them would ban
  React. Instead, ESLint limits how deeply callbacks nest, and the strict rule
  sets ban `any`, so every callback has a checked type.

What ESLint cannot see: recursion (rule 1) is not checked automatically, so
code review watches for it; the web UI has none. And like Python's checker,
ESLint can't prove that what a `for...of` walks over is small: that is what the
size caps of rule 3 are for.

The tests in `frontend/` may be longer than 60 lines and nest callbacks
(`describe`, `it`), as pytest tests may break rules 5, 6 and 9. They pass every
other check. Suppressions follow the same policy as in Python: an
`eslint-disable` comment names one rule and gives its reason after ` -- `, and
ESLint reports one that no longer does anything. The web UI has none.

## Running the checker

From the repository root, `make jpl` runs:

```bash
cd backend && uv run python -m tools.power_of_ten app tools
```

It prints one line per problem, then a summary:

```text
app/datastore.py:42:5: R2 `while` loop: loop with `for` over something of fixed size
Power of Ten: 18 files, 161 functions, 0.53 checks per function, 1 problem.
```

The exit code is 0 when every rule holds, 1 when a rule is broken, and 2 when
the input is bad, for example a path that does not exist or a file that is not
valid Python.

The checker follows its own rules: it has no recursion and no `while` loops,
and it caps the number of files, the size of each file and the size of every
walk over a syntax tree. Its tests are in `backend/tests/test_power_of_ten.py`.

## What the checker cannot see

The checker reads code; it does not run it. That gives it some blind spots,
which code review covers:

- **Calls it cannot resolve.** When it cannot tell the class of an object, for
  example the result of a library call, it cannot follow a method call on that
  object. Recursion through such a call is not found.
- **Callbacks from libraries.** If our code gives a library a method that the
  library later calls back, the checker does not see that call.
- **Protocols.** A call through a `Protocol` is treated as a call to every class
  in the checked code that has a method of that name. This can report a cycle
  that cannot happen at run time; split the method names if that occurs.
- **The size of what a `for` loop walks over.** Rule 2 is satisfied by `for`,
  but the checker cannot prove that the thing being looped over is finite. Loop
  over capped results and fixed ranges.
- **Reads it does not know.** Rule 3 knows the common Python and pandas read
  calls, not every library's.
- **Density is an average.** Rule 5 counts checks across all the code, so one
  function with no checks is allowed if others make up for it.

## Suppressions

Sometimes a tool reports something that is not a real problem in one specific
place. You may silence that one check on that one line, but only with the exact
code and a written reason:

```python
proc = subprocess.run(cmd, check=False)  # noqa: S603 -- cmd is built by our code, not the AI
value = parse(raw)  # type: ignore[arg-type]  # the library's type stubs are wrong here
```

- **One specific code.** Ruff's `PGH` rules and mypy's `ignore-without-code`
  reject a blanket `# noqa` or `# type: ignore`.
- **A reason.** The Power of Ten checker reports `R10` for a `# noqa`,
  `# type: ignore` or `# pyright: ignore` comment without a reason. Write the
  reason after ` -- `, or in a second comment right after the suppression.
- **No dead suppressions.** Ruff reports a `# noqa` that no longer does anything
  (`RUF100`), and basedpyright reports an unnecessary `# type: ignore`.

The Power of Ten checker itself has no suppression comments. A rule it reports
is fixed in the code. Before you suppress anything else, try to fix the cause;
a reviewer checks every reason.

## Changing this standard

A change to these rules is a change to how the whole project is built, so it
goes through a pull request like any other change:

1. Update this file first, so it stays the source of truth.
2. Update the checker in `backend/tools/power_of_ten.py`, with tests in
   `backend/tests/test_power_of_ten.py` for what it must report and what it
   must allow.
3. Fix any code that the new rule reports, in the same pull request.
4. Update the summaries in CONTRIBUTING.md and LEARNING.md.

Rules may get stricter over time. Raising the check density when the code
allows it is always welcome; loosening a rule needs a written reason in the pull
request.

## References

- Gerard J. Holzmann, "The Power of Ten: Rules for Developing Safety Critical
  Code", *IEEE Computer*, June 2006:
  <https://spinroot.com/gerard/pdf/P10.pdf>
- [Ruff rules](https://docs.astral.sh/ruff/rules/)
- [mypy: the `--strict` flag](https://mypy.readthedocs.io/en/stable/command_line.html)
- [basedpyright: `reportUnusedCallResult`](https://docs.basedpyright.com/latest/configuration/config-files/)
