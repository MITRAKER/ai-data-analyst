# Contributing to AI Data Analyst

Thank you for your interest in this project. AI Data Analyst is a portfolio and
learning project. It is built step by step, and [LEARNING.md](LEARNING.md)
teaches each step. It is also built the way a professional team works, with
automated checks on every change. This guide shows you how that works, from your
first setup to a merged pull request.

New to open source? You are welcome here. A small pull request is a good way to
start: a typo fix, a clearer sentence in a lesson, or a missing test.

Everyone who takes part follows the [code of conduct](CODE_OF_CONDUCT.md). If you
find a security problem, please do not open an issue. Follow
[SECURITY.md](SECURITY.md) instead.

## Contents

- [Before you start](#before-you-start)
- [Prerequisites](#prerequisites)
- [First-time setup](#first-time-setup)
- [Everyday workflow](#everyday-workflow)
- [Quality gates](#quality-gates)
- [Coding standard](#coding-standard)
- [Testing guidelines](#testing-guidelines)
- [Adding a dependency](#adding-a-dependency)
- [Suppressions policy](#suppressions-policy)
- [Release process](#release-process)
- [Getting help](#getting-help)
- [License](#license)

## Before you start

For anything bigger than a small fix, please open an issue first and describe
what you want to change. Then we can agree on the idea before you spend time on
the code.

Where things are:

| Path | What it holds |
| --- | --- |
| `backend/app/` | The application: the API, the datastore, the SQL guard and the AI agent |
| `backend/tests/` | The tests |
| `backend/tools/power_of_ten.py` | Our checker for the Power of Ten rules |
| `backend/pyproject.toml`, `backend/uv.lock` | The dependencies, their exact locked versions, and the settings of the Python tools |
| `frontend/src/` | The web UI (Next.js and TypeScript): the page, its components, and the server routes in `src/app/api/` that pass requests on to the API |
| `frontend/src/**/*.test.ts(x)`, `frontend/e2e/` | The web UI's unit and component tests (Vitest), and its browser tests (Playwright) |
| `frontend/package.json`, `frontend/package-lock.json` | The web UI's packages and their exact locked versions |
| `compose.yaml` | Docker Compose: the web UI and the API together |
| `data/sample_sales.csv` | A sample dataset to try things with |
| `docs/CODING_STANDARD.md` | The coding standard |
| `scripts/` | Shell scripts: the smoke tests for the Docker image and for Docker Compose, and the release-notes helper |
| `.github/` | The CI, release and CodeQL workflows, Dependabot, and the issue and pull request templates |
| `Makefile` | The short commands, such as `make check` (run `make` to list them) |
| `LEARNING.md` | One lesson for each build step |

## Prerequisites

| Tool | Version | Why you need it |
| --- | --- | --- |
| [git](https://git-scm.com/downloads) | A recent version | To get the code and track your changes |
| [Python](https://www.python.org/downloads/) | 3.12 or newer | The backend's language. uv can install it for you |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | A recent version. CI and Docker use 0.13.8 | Installs the packages and runs the tools |
| make | Any | Runs the short commands in the `Makefile`, such as `make check` |
| [Node.js](https://nodejs.org/) | 26, the version in `frontend/.nvmrc` (24.15 or newer works) | Only for the web UI. npm comes with it |
| [Docker](https://docs.docker.com/get-started/get-docker/) | Optional | Only for the container images and Docker Compose (`make docker`, `make up`) |

Some tips:

- **Python:** uv reads `backend/.python-version` (3.13) and downloads that
  version if your computer does not have it. CI tests on Python 3.12, 3.13,
  3.14 and 3.15.
- **uv:** to install the exact version CI uses on macOS or Linux, run
  `curl -LsSf https://astral.sh/uv/0.13.8/install.sh | sh`.
- **make:** on macOS, `xcode-select --install` installs it. On Linux, use your
  package manager, for example `sudo apt install make`. On Windows, use WSL (the
  Windows Subsystem for Linux) and run every command inside it.
- **Node.js:** a version manager such as [nvm](https://github.com/nvm-sh/nvm)
  or [fnm](https://github.com/Schniz/fnm) reads `frontend/.nvmrc` and installs
  that version: run `nvm install` (or `fnm use`) inside `frontend/`.
- **An Anthropic API key** is optional. You only need one to run the real agent
  with `POST /ask` or the terminal CLI. The tests never use it.

## First-time setup

If you do not have write access to the repository, first fork it on GitHub (the
**Fork** button at the top right of the repository page). Then clone your fork
instead: in the URL below, replace `MITRAKER` with your GitHub user name.

```bash
git clone https://github.com/MITRAKER/ai-data-analyst.git
cd ai-data-analyst
cp .env.example .env    # then add your ANTHROPIC_API_KEY, if you have one
make setup
```

`make setup` does two things:

1. It runs `cd backend && uv sync --locked --all-groups`. This creates a virtual
   environment in `backend/.venv` and installs the exact versions listed in
   `backend/uv.lock`, including the developer tools. `--locked` stops with an
   error if `uv.lock` does not match `pyproject.toml`.
2. It installs the pre-commit hooks, so that checks run on your files before each
   commit.

Now check that everything works:

```bash
make check   # runs every backend check that CI runs; all of them should pass
make run     # starts the development server on port 8000
```

While the server runs, open <http://localhost:8000/docs> to try the API in your
browser. <http://localhost:8000/health> should return `{"status": "ok"}`. Stop
the server with Ctrl+C.

`.env` is ignored by git, so your key stays on your computer. Never commit it.

To work on the web UI, install its packages too, and start it while the API
runs:

```bash
make web-setup   # npm ci: the exact versions in frontend/package-lock.json
make web-check   # formatting, lint, types and unit tests (CI also builds the app and runs npm audit)
make web-dev     # starts the web UI on http://localhost:3000, with hot reload
```

`frontend/.npmrc` turns off install scripts, so no package can run code on your
computer while it is installed. For the browser tests, install Chromium once
with `cd frontend && npx playwright install chromium`, then run `make web-e2e`.

To run any tool inside the project's environment, use `uv run` from the
`backend/` folder, for example `cd backend && uv run pytest`.

## Everyday workflow

```bash
git switch main && git pull                 # 1. start from the latest main
git switch -c fix/empty-csv-upload          # 2. create a branch
                                            # 3. make your change, with tests
make format                                 # 4. fix what can be fixed automatically,
make check                                  #    then run every backend check
                                            #    (make web-check for the web UI)
git status                                  # 5. see what changed
git add <the files you changed>
git commit -m "fix: reject CSV files that have no rows"
git push -u origin fix/empty-csv-upload     # 6. push, then open a pull request
```

Step by step:

1. **Start from the latest `main`**, so that your branch has everyone else's
   recent changes. If you work in a fork, first click **Sync fork** on your
   fork's GitHub page, so that its `main` matches this repository.
2. **Create a branch.** Name it `<type>/<short-name>`, with the same types as
   [commit messages](#commit-messages), for example `feat/describe-column`,
   `fix/duplicate-columns` or `docs/contributing-guide`.
3. **Make your change.** Keep each pull request to one topic. Add or update tests
   with every code change.
4. **Run the checks.** `make format` fixes what can be fixed automatically, such
   as formatting. `make check` runs everything CI runs on the backend. For the
   web UI, `cd frontend && npm run format` fixes the formatting, and
   `make web-check` runs its checks.
5. **Commit** with a [Conventional Commit](#commit-messages) message. The
   pre-commit hooks run at this point. If a hook fails, the commit does not
   happen: fix the problem, `git add` the files again and commit again. If a hook
   changed a file for you, `git add` that file and commit again.
6. **Push and open a pull request.** After the push, GitHub shows a link to open a
   pull request. The [pull request template](.github/pull_request_template.md)
   fills in the description: complete each section.
7. **Wait for CI and the review.** CI runs every [quality gate](#quality-gates).
   If a check fails, open its **Details** link to read the log, fix the problem
   and push again. The maintainer reviews every pull request.

### Commit messages

Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). The
format is `<type>: <summary>`, or `<type>(<scope>): <summary>` with an optional
scope. Write the summary as a command ("add", not "added"), and keep it short.

| Type | Use it for |
| --- | --- |
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `test` | Adding or fixing tests only |
| `refactor` | A code change that does not change behavior |
| `perf` | A change that makes the code faster or use less memory |
| `ci` | The CI workflows |
| `build` | Dependencies, packaging or the Docker image |
| `chore` | Other maintenance |

Examples:

- `feat: add a describe_column tool`
- `fix(datastore): give every duplicate column a unique name`
- `docs: explain prompt caching in lesson 2`

Mark a breaking change with a `!` after the type, as in
`feat!: rename the ask endpoint`. Then explain the change in a
`BREAKING CHANGE:` line at the end of the commit message.

### Pull requests

- Give the pull request a Conventional Commit title too, such as
  `fix: reject CSV files that have no rows`.
- Link the issue it solves, for example "Closes #12". GitHub then closes the
  issue when the pull request is merged.
- Keep it small. A pull request that does one thing is faster to review.
- Not finished yet? Open it as a draft pull request to get early feedback.

### Changelog entries

If people who use or study the project would notice your change, add a line to
[CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]`, in the right group:
`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` or `Security`. Write it for a
reader, not as a commit message. At release time, this section becomes the
release notes.

## Quality gates

Every pull request must pass these checks before it is merged. `make check` runs
all the backend checks on your computer, so you can find problems before CI does.
A few checks run only in CI.

| Check | What it checks | Run it locally | What a failure usually means |
| --- | --- | --- | --- |
| Ruff lint | Likely bugs, unused code, import order, naming, docstrings, complexity and security problems. Ruff's `S` rules are the Bandit security checks. | `make lint` | The message names a rule, such as `F401` (unused import). `cd backend && uv run ruff rule F401` explains it. Fix the code, or see the [suppressions policy](#suppressions-policy). |
| Ruff format | One consistent layout for all Python code, with lines up to 100 characters | `make lint` checks it, `make format` fixes it | The code was not formatted. Run `make format` and commit the result. |
| mypy (strict) | Type hints: every function is annotated, and every value is used in a way its type allows | `make typecheck` | A value may have the wrong type, a value may be `None` where the code does not expect it, or a type hint is missing. Fix the code or the hint. |
| basedpyright | A second type checker (a fork of Microsoft's pyright), with its `reportUnusedCallResult` check turned on (JPL rule 7: never ignore a return value) | `make typecheck` | You called a function and dropped its result. Use the result, or write `_ = f()` if you truly do not need it. It can also report a type error that mypy did not catch. |
| Power of Ten checker | The NASA/JPL Power of Ten rules, adapted to Python (see [Coding standard](#coding-standard)) | `make jpl` | The code breaks one of the rules, for example with a `while` loop, recursion or a function longer than 60 lines. [docs/CODING_STANDARD.md](docs/CODING_STANDARD.md) explains each rule. |
| pytest + coverage | All tests pass, warnings count as errors, and branch coverage is at least 95% | `make test` | A test failed, the code raised a warning, or new code has no tests. The coverage report lists the lines that no test reached. |
| pip-audit | Known vulnerabilities in the packages we depend on | `make security` (needs internet access) | A package we use has a published vulnerability. Upgrade it to a fixed version (see [Adding a dependency](#adding-a-dependency)). Often a Dependabot pull request already does this. |
| CodeQL | Deep security analysis of the Python code, the TypeScript code and the GitHub Actions workflows | CI only, on every pull request and once a week | CodeQL found a path where untrusted input reaches something dangerous, or a risky workflow pattern. Open the alert to see the path and how to fix it. |
| pre-commit hooks | File hygiene (whitespace, line endings, valid YAML and TOML, no large files, executable scripts), secrets (detect-secrets and detect-private-key), ShellCheck for the shell scripts, zizmor for the security of the GitHub Actions files, and the JSON schemas of the workflow, action and Dependabot files | Runs on each `git commit`. To check every file: `cd backend && uv run pre-commit run --all-files` (the web UI's hooks need `make web-setup` first, or skip them with `SKIP=web-format,web-lint`) | A hook fixed a file for you: `git add` it and commit again. Or it found something that looks like a secret: remove it. If a real key was committed, follow [SECURITY.md](SECURITY.md#if-a-key-leaks). For ShellCheck and zizmor, the message names a rule and links to its explanation. |
| Docker image | The image builds. A smoke test starts it, waits for its health check, checks that the app runs as an ordinary user who cannot change the installed code, uploads the sample CSV, runs a query, and runs Python in the sandbox | `make docker smoke` (needs Docker) | The Dockerfile or the app's startup is broken. A common cause: the app imports a package that is only in the `dev` group, which the image does not install. The job prints the container's log. |
| Prettier | One consistent layout for the web UI's code | `cd frontend && npm run format:check`; `npm run format` fixes it | The code was not formatted. Run `npm run format` in `frontend/` and commit the result. |
| ESLint | Likely bugs, React and accessibility mistakes, and the Power of Ten rules for TypeScript, with `--max-warnings=0` | `cd frontend && npm run lint` | The message names a rule, such as `complexity` or `@typescript-eslint/no-floating-promises`. [docs/CODING_STANDARD.md](docs/CODING_STANDARD.md#the-web-ui-typescript) maps the rules. |
| TypeScript | Strict types for all of the web UI's code | `cd frontend && npm run typecheck` | A value may be `undefined` or of another type than the code expects. Check it with code; never silence it with `as`. |
| Vitest + coverage | The web UI's unit and component tests pass, with at least 95% coverage of lines, branches and functions | `cd frontend && npm run test:coverage` | A test failed, or new code has no tests. Open `frontend/coverage/index.html` to see what no test reached. |
| Build and npm audit | The production build works; no locked package has a known vulnerability; every package carries the npm registry's signature | `cd frontend && npm run build && npm audit && npm audit signatures` | The build output names the file. For `npm audit`, upgrade the package (see [Adding a dependency](#adding-a-dependency)). |
| Playwright | Browser tests in Chromium, on a desktop and a phone screen: asking, Stop, errors, uploads, security headers, and accessibility (axe) | `make web-e2e` (install Chromium first, see [First-time setup](#first-time-setup)) | The test's name says what broke. In CI, the report with a screenshot of each failure is attached to the run. axe names the accessibility rule and the element. |
| Docker Compose | Both images build and work together: uploads through the web UI's server, the size limit, the missing-key message, the sandbox in the read-only API container, data kept across a restart, and that only the web UI can be reached | `make compose-smoke` (needs Docker) | The script prints the logs of both services. Check `compose.yaml` and the Dockerfiles. |

CI runs the tests on Python 3.12, 3.13, 3.14 and 3.15. Locally, `make test` uses
the version in `backend/.python-version`.

CI also has a job called **All checks passed**, which passes only when every
other CI job passed. Branch protection on `main` should require that one check,
plus CodeQL, instead of listing every job.

Two hooks run before each `git push` instead of each commit: the backend's full
test suite, and, when files in `frontend/` changed, the web UI's format, lint,
type and unit-test checks (`make web-check`). So a push with failing tests stops
on your computer, not in CI. The web UI's hooks use its packages, so run
`make web-setup` before you change files there; without them, the hooks stop
and say so.

## Coding standard

The backend follows the NASA/JPL "Power of Ten" rules, adapted to Python. Gerard
Holzmann wrote the original rules at NASA's Jet Propulsion Laboratory (JPL) for
safety-critical C code. Their ideas carry over well: code that is simple, bounded
and explicit is easier to read, test and check by machine.

Our own checker, `backend/tools/power_of_ten.py`, checks the code against these
rules. `make jpl` runs it with
`cd backend && uv run python -m tools.power_of_ten app tools`. Some rules also
rely on the other quality gates, such as basedpyright for rule 7.

The rules in short:

1. **Simple control flow:** no recursion (the checker finds call cycles), a
   complexity limit of 10 per function, and no goto-like tricks.
2. **Every loop has a fixed upper bound:** no `while` loops, no
   `itertools.count`, `itertools.cycle` or `itertools.repeat` without a count, and
   no two-argument `iter()`.
3. **No unbounded memory growth after startup:** every input, result and buffer
   has a size cap. Read files with `read_capped()` from `backend/app/files.py`,
   never with `read_text()` or a bare `.read()`.
4. **Short functions:** at most 60 lines of code each (the docstring, comments
   and blank lines do not count).
5. **Assertions:** check inputs and invariants with `require(...)` from
   `backend/app/invariants.py`. Never use a bare `assert` in app code, because
   `python -O` removes asserts. Across all the code, there must be at least 0.5
   checks (`raise`, `require()` or `assert_never()`) per function on average.
6. **Smallest possible scope:** no `global` or `nonlocal`, and no mutable
   module-level state.
7. **Check every return value:** never ignore a function's result. Write
   `_ = f()` when a result is truly not needed. Never swallow an exception with
   `except ...: pass` or `contextlib.suppress`.
8. **Limited metaprogramming** (the Python stand-in for the C preprocessor): no
   `eval`, `exec`, `compile`, `__import__`, `getattr`/`setattr`, `importlib`,
   `pickle`, metaclasses or dunder attributes such as `obj.__class__`.
9. **Limited indirection** (the Python stand-in for pointers): no lambdas, no
   functions stored in variables or passed as values, and no `Callable` type
   hints. Pass an object that has the method instead.
10. **Zero warnings:** every linter, type checker and test runs with warnings as
    errors, on every change and once a week. Every suppression comment gives a
    reason.

The web UI follows the same ten rules in TypeScript, checked by ESLint and
strict TypeScript. Two rules take a different form there: values from outside
are checked by type guards instead of `require()`, and callbacks are allowed,
because React is built on them.

The full rules are in [docs/CODING_STANDARD.md](docs/CODING_STANDARD.md). That
file is the source of truth; this list is only a summary.

## Testing guidelines

- **Tests never call the real Claude API or the network.** They use a fake client
  that returns scripted replies. Follow the pattern in
  [backend/tests/test_agent.py](backend/tests/test_agent.py): write the replies
  you expect from Claude (tool calls, then a final answer), pass the fake client
  to the agent, and check what the agent did. Tests stay free and fast, and they
  give the same result on every run. No API key is needed.
- **Keep coverage at 95% or more.** `make test` measures branch coverage of `app`
  and `tools`, and fails below 95%. The report lists the lines and branches that
  no test reached. Add tests for them; do not lower the bar.
- **Test failure paths, not just happy paths.** Many bugs hide in error handling.
  For example, test SQL the guard must refuse, Python the sandbox must block, a
  timeout, an empty or broken CSV file, a refusal or an API error from Claude,
  and every limit, such as too many steps or too many rows.
- **Warnings are errors.** If your change makes Python or a library print a
  warning, such as a `DeprecationWarning`, the test run fails. Fix the cause.
- **Tests are type-checked too.** mypy and basedpyright also check `tests/`, so
  annotate test functions and fixtures, for example
  `def test_health(client: TestClient) -> None:`.
- **Keep tests independent.** Give each test its own in-memory `DataStore`, as
  the existing fixtures do, so that no test can affect another.

While you work, run one test file, or only the tests whose names contain a word:

```bash
cd backend
uv run pytest tests/test_api.py --no-cov
uv run pytest -k sandbox --no-cov
```

`--no-cov` turns off the coverage check, which only makes sense for the full test
suite. Run `make test` before you push.

### The web UI's tests

- **Find elements the way people do.** Use Testing Library's `getByRole` and
  `getByLabelText`, such as `getByRole("button", { name: "Stop" })`, not CSS
  classes. A test that can't find a control by its name points to a control
  that a screen reader can't name either.
- **No real network.** Unit tests replace `fetch` with `vi.stubGlobal`; the
  helpers in `frontend/src/test/fakes.ts` build fake responses and event
  streams. The browser tests use `frontend/e2e/fake-api.mts` in place of the
  Python API, so they need no key either.
- **Test the pure logic directly.** The parser (`sse.ts`), the reducer
  (`conversation.ts`) and the checks of every event (`events.ts`) are plain
  functions: call them, and check the result.
- **Every browser test fails on a console error**, and the main pages are
  checked with axe. Add `expectAccessible(page)` to a new browser test that
  shows something new.

```bash
cd frontend
npx vitest src/lib/sse.test.ts       # one file, rerun on every change
npm run build && npx playwright test e2e/chat.spec.ts --project desktop   # build first, then one file, one screen size
```

## Adding a dependency

Every new package is code that we have to trust, keep up to date and ship in the
Docker image. So first check whether the standard library, or a package we
already use, can do the job. If you still need a new package, add it with uv:

```bash
cd backend
uv add <package>                # needed when the app runs
uv add --group dev <package>    # only needed to develop or test, such as a pytest plugin
```

`uv add` updates `pyproject.toml` and `uv.lock`, and installs the package. Commit
`uv.lock` together with `pyproject.toml`, for example as
`build(deps): add <package>`. Never edit `uv.lock` by hand. Then run
`make check`.

Which group? If code in `backend/app/` imports the package, the app needs it when
it runs: use `uv add <package>`. The Docker image installs only those runtime
dependencies, not the `dev` group. If a package the app needs is in the wrong
group, the app fails to start inside the image, and the Docker smoke test in CI
catches it.

Other useful commands, run from `backend/`:

- `uv remove <package>` removes a dependency.
- `uv lock --upgrade-package <package>` upgrades one package to the newest version
  that `pyproject.toml` allows. Then `uv sync --all-groups` installs it.

For the web UI, from `frontend/`:

```bash
npm install <package>              # needed by the app in the browser or on its server
npm install --save-dev <package>   # only needed to develop or test
```

`frontend/.npmrc` makes npm save the exact version and run no install scripts.
Commit `package-lock.json` together with `package.json`. Prefer a version that
has been out for at least a week: a malicious release is usually found and
removed within days, which is also why Dependabot waits 7 days before it
proposes a new version. The Docker image installs every package to build the
app, but ships only what the built server uses.

Dependabot also opens pull requests every week to keep the dependencies up to
date.

## Suppressions policy

Sometimes a tool reports a problem that is not real in one specific place. You
may silence the check on that line, but only with:

- **One specific code.** Name the exact rule: `# noqa: <CODE>` for Ruff, or
  `# type: ignore[<code>]` for the type checkers. Never a blanket `# noqa` or
  `# type: ignore`.
- **A written reason on the same line**, so that the next reader knows why it is
  safe.

```python
# The pattern
result = f()  # noqa: <CODE> -- <reason>
result = f()  # type: ignore[<code>]  # <reason>

# Allowed: one specific code, and a reason on the same line
proc = subprocess.run(cmd, check=False)  # noqa: S603 -- cmd is built by our code, not the AI

# Not allowed: a blanket suppression, or no reason
proc = subprocess.run(cmd, check=False)  # noqa
proc = subprocess.run(cmd, check=False)  # noqa: S603
```

Ruff and mypy already reject suppressions without a code (Ruff's `PGH` rules and
mypy's `ignore-without-code` check). The Power of Ten checker rejects a
suppression without a reason (rule 10). Ruff also reports a `# noqa` that no
longer does anything (`RUF100`), and basedpyright reports a `# type: ignore` that
is not needed. Code review checks that the reason is a good one. The same policy
applies to `# pyright: ignore[<rule>]` comments.

The Power of Ten checker itself cannot be silenced: fix what it reports.

Before you suppress anything, try to fix the cause. For an unused return value
(rule 7), do not suppress the warning: write `_ = f()`.

## Release process

Releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
`MAJOR.MINOR.PATCH`. Bump PATCH for bug fixes, MINOR for new features, and MAJOR
for changes that break existing use. While the version starts with `0`, the
project is in early development, and anything may change.

The maintainer makes each release in five steps:

1. Bump `__version__` in `backend/app/__init__.py`.
2. Move the "Unreleased" notes in `CHANGELOG.md` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section. Leave an empty `## [Unreleased]` section
   above it, and update the links at the bottom of the file (example below).
3. Preview the release notes: `scripts/release-notes.sh X.Y.Z` prints exactly
   what the GitHub Release will say.
4. Merge to `main` through a pull request.
5. Tag the merged commit and push the tag:

```bash
git switch main && git pull
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
```

The release workflow (`.github/workflows/release.yml`) then:

- checks that the tag is a version it can release (see below), that it matches
  `__version__`, and that `CHANGELOG.md` has notes for the version;
- runs the full CI again, on the tagged commit;
- builds the Docker image for `linux/amd64` and `linux/arm64`, with provenance
  and an SBOM attached, and publishes it as
  `ghcr.io/mitraker/ai-data-analyst:X.Y.Z` and `:latest`;
- only then creates the GitHub Release, using that `CHANGELOG.md` section as the
  release notes. If the image fails, nothing has been announced yet: fix the
  problem, then use **Re-run failed jobs** on the workflow run.

**Version numbers** use the standard spelling of
[PEP 440](https://peps.python.org/pep-0440/): `X.Y.Z`, optionally followed by
`aN`, `bN` or `rcN` (a pre-release), `.postN` and `.devN`. The workflow refuses
other spellings, such as the SemVer style `v0.3.0-rc.1` or `v0.3.0RC1`, because
they would hide that the version is a pre-release.

**Pre-releases** have `aN`, `bN`, `rcN` or `.devN` in their version, such as
`0.3.0rc1` (tag `v0.3.0rc1`), `0.3.0a1` or `0.3.0b1`. The workflow marks the
GitHub Release as a pre-release and does not move the image's `:latest` tag.

**The first release:** GitHub may create the image's package as private. To let
anyone pull the image, open the package from your GitHub profile (**Packages**),
then **Package settings** > **Change visibility** > **Public**.

**uv's version** is written in two places: `.github/actions/setup-backend/action.yml`
(CI) and `backend/Dockerfile`. Change both together.

The links at the bottom of `CHANGELOG.md` look like this after a release:

```text
[Unreleased]: https://github.com/MITRAKER/ai-data-analyst/compare/vX.Y.Z...HEAD
[X.Y.Z]: https://github.com/MITRAKER/ai-data-analyst/releases/tag/vX.Y.Z
```

## Getting help

Stuck, or not sure how something works? Open a GitHub issue:
<https://github.com/MITRAKER/ai-data-analyst/issues/new/choose>. If something
does not work, use the bug report form. Say what you tried, what happened and
what you expected, and add any error output with the API keys removed. For a new
idea, use the feature request form.

[LEARNING.md](LEARNING.md) explains how each part of the project works and why it
was built that way, so it may answer your question too.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE), like the rest of the project.
