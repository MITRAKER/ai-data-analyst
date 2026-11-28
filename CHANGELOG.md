# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Backend (step 1):** FastAPI API to upload CSV files into DuckDB (column names cleaned, ISO dates parsed), list datasets, inspect schema with sample rows, and run read-only SQL; SQL guard that uses DuckDB's parser to allow only a single `SELECT`; DuckDB with external file access disabled; row caps with a truncation flag; sample dataset `data/sample_sales.csv`.
- **AI agent (step 2):** Claude tool-use loop that reports every step; tools `query_database`, `run_python` and `make_chart` (Plotly JSON); Python sandbox (AST allow-list, separate process, time/CPU/memory/file-size limits, no new file descriptors, processes or threads, and an audit hook that refuses files, processes, signals, sockets and `ctypes`); terminal CLI (`python -m app.cli`); `POST /ask` endpoint; adaptive thinking, prompt caching and server-side refusal fallbacks.
- **CI:** every pull request, every push to `main` and a weekly run check the code with Ruff, mypy (strict), basedpyright, the NASA/JPL Power of Ten checker, and the tests on Python 3.12, 3.13, 3.14 and 3.15 (warnings as errors, at least 95% branch coverage); audit the locked dependencies with pip-audit; run the pre-commit hooks on every file; and build and smoke-test the Docker image. One "All checks passed" job sums them up for branch protection.
- **Releases:** pushing a version tag checks it against `__version__` and this changelog, runs CI again, creates a GitHub Release with the notes from this file, and publishes the Docker image for `linux/amd64` and `linux/arm64`, with provenance and an SBOM, to `ghcr.io`.
- **Coding standard:** `docs/CODING_STANDARD.md` adapts the NASA/JPL "Power of Ten" rules to Python, and `backend/tools/power_of_ten.py` checks them (recursion through a call graph, unbounded loops and reads, function length, `require()` instead of `assert` and a minimum check density, mutable global state, swallowed errors, metaprogramming, functions as values, and a reason for every suppression).
- **Security tooling:** CodeQL for the Python code and the workflows; zizmor for the workflows; detect-secrets and detect-private-key; Dependabot for Python packages, GitHub Actions and the Docker base image, with a 7-day cooldown; least-privilege workflow permissions and no third-party actions.
- **Developer tooling:** uv with a lockfile; a `Makefile` (`make check`, `make test`, `make run` and more); pre-commit hooks for file hygiene, secrets, ShellCheck, zizmor and the schemas of the GitHub files; EditorConfig.
- **Docker image:** multi-stage build that runs as a non-root user who cannot change the installed code, with a health check and an optional `/data` volume for a DuckDB file that outlives the container.
- **Documentation:** Lesson 3 in `LEARNING.md`; `CONTRIBUTING.md`, `SECURITY.md` and `CODE_OF_CONDUCT.md`; issue and pull request templates; `CODEOWNERS`.
- **Chat interface (step 3):** a Next.js web UI in `frontend/`. Upload a CSV and see its columns and first rows; ask a question and watch each step of the agent while it happens (its plan, the SQL and Python it runs, the result tables); see the answer with interactive Plotly charts; stop an answer with the Stop button. Light and dark mode, and a layout for phones.
- **Streaming API:** `POST /ask/stream` sends each step of the agent as a Server-Sent Event while it happens, with a keep-alive ping; the agent stops after its current step when the client disconnects. The stream always ends with an `answer` or `error` event, even when the agent fails unexpectedly. `GET /agent/status` says whether the agent can answer, and why not.
- **Web UI security:** the browser talks only to the web UI's own server, which passes on just the calls the page needs; that server refuses uploads and questions that another website's page sends through your browser (cross-site request forgery), and host names other than this computer's own unless they are listed in `ALLOWED_HOSTS` (DNS rebinding), on every page and every route but `/api/health`; the API refuses both itself too, wherever it runs (with `make run`, a browser can reach it directly), and in Docker Compose it answers to `api` only because `compose.yaml` adds that name; a Content-Security-Policy with a new nonce for every page, the page-not-found page included, a policy that allows nothing for the API's routes, and headers against framing and content sniffing; every response is checked at run time, text from the agent is never inserted as HTML, and the text of charts is escaped, so a CSV cell can't become a link.
- **Docker Compose:** `docker compose up --build` (or `make up`) runs the web UI and the API together. Only the web UI is published, on `127.0.0.1`; both containers are read-only, run as ordinary users and have no Linux capabilities. A smoke test checks all of this.
- **Web UI checks in CI:** Prettier, ESLint with the Power of Ten rules for TypeScript, strict TypeScript, unit and component tests with a 95% coverage gate, a production build, `npm audit` and npm's registry signatures; Playwright browser tests on a desktop and a phone screen, with axe accessibility checks; the Compose smoke test. CodeQL also scans the TypeScript code, Dependabot updates the npm packages and the Node.js image, and pre-commit runs Prettier and ESLint.
- **Documentation:** Lesson 4 in `LEARNING.md`, and a TypeScript section in `docs/CODING_STANDARD.md`.

### Changed

- Dependencies are managed with uv, in `backend/pyproject.toml` and `backend/uv.lock`, instead of `requirements.txt` files.
- The API no longer sends CORS headers, and `CORS_ORIGINS` is gone from `.env.example`. Browsers reach the API only through the web UI's server, so it needs none.

### Fixed

- A version tag spelled the SemVer way, such as `v0.3.0-rc.1`, would have been published as a final release and moved the image's `:latest` tag. The release workflow now accepts only the standard PEP 440 spelling and refuses the rest.
- The release workflow created the GitHub Release before the image was pushed, so a failed image would have left a release without its image. It now pushes the image first. The image on ghcr.io also gets its description, which an image for several platforms takes from index annotations, not labels.
- Duplicate column names after cleaning could still collide (for example a, a and a_1); every column now gets a unique name.
- `make_chart` with an empty `y` column name failed with "Internal error in tool make_chart"; it now tells the agent what to fix.
- A very large tool result was sent to Claude whole. Tool results are now cut at 50,000 characters, with a note that asks the agent to select fewer columns or aggregate.
- The `.env` file and the CLI's input files were read whole, however large; they are now read with a size limit.
- A question of only spaces got past the 3-character minimum. Spaces around a question are now removed before it is checked.

### Security

- AI-written Python could get past the sandbox's static check with `from random import _os` or `from collections import _sys`, which hand over the modules those allowed modules use inside, or through attributes such as `re.enum.bltns` and generator frames. It could then open files by first closing a file descriptor it already had, and so read the server's API key from `/proc`. Names imported with `from ... import` now follow the attribute rules, the child process may open no new file descriptor at all and start no process or thread, and an audit hook refuses files, processes, signals, sockets, `ctypes` and the modules that could get around the limits. Tests run code that the static check would refuse, to show that the other layers hold on their own.
- Code that got past the static check could also get around the sandbox's audit hook. On Python 3.14, pandas loads the module that starts subinterpreters, which run without the hook. Some Python builds also include Python's test modules, which can start them too, and Python makes a module that is built into it without asking the hook. Python 3.14 also added `sys.remote_exec()`, which asks another Python process, such as the server, to run a script. And Python removes the hook while it shuts down, so a `__del__` method could run after that and, for example, send a signal to the server. The child process now never loads those modules, cannot load a new module written in C once the code starts, and refuses `sys.remote_exec()` and the `_remote_debugging` module, which reads the memory of other processes. It ends at once when the code is done, without Python's normal shutdown, and if the code blocks that, the hook ends the process just before Python would remove it. The hook also refuses changes to the default arguments of a function as well as to its code.

[Unreleased]: https://github.com/MITRAKER/ai-data-analyst/commits/main
