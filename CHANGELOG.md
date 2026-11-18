# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Backend (step 1):** FastAPI API to upload CSV files into DuckDB (column names cleaned, ISO dates parsed), list datasets, inspect schema with sample rows, and run read-only SQL; SQL guard that uses DuckDB's parser to allow only a single `SELECT`; DuckDB with external file access disabled; row caps with a truncation flag; sample dataset `data/sample_sales.csv`.
- **AI agent (step 2):** Claude tool-use loop that reports every step; tools `query_database`, `run_python` and `make_chart` (Plotly JSON); Python sandbox (AST allow-list, separate process, time/CPU/memory/file-size limits); terminal CLI (`python -m app.cli`); `POST /ask` endpoint; adaptive thinking, prompt caching and server-side refusal fallbacks.
- **CI:** every pull request, every push to `main` and a weekly run check the code with Ruff, mypy (strict), basedpyright, the NASA/JPL Power of Ten checker, and the tests on Python 3.12, 3.13 and 3.14 (warnings as errors, at least 95% branch coverage); audit the locked dependencies with pip-audit; run the pre-commit hooks on every file; and build and smoke-test the Docker image. One "All checks passed" job sums them up for branch protection.
- **Releases:** pushing a version tag checks it against `__version__` and this changelog, runs CI again, creates a GitHub Release with the notes from this file, and publishes the Docker image for `linux/amd64` and `linux/arm64`, with provenance and an SBOM, to `ghcr.io`.
- **Coding standard:** `docs/CODING_STANDARD.md` adapts the NASA/JPL "Power of Ten" rules to Python, and `backend/tools/power_of_ten.py` checks them (recursion through a call graph, unbounded loops and reads, function length, `require()` instead of `assert` and a minimum check density, mutable global state, swallowed errors, metaprogramming, functions as values, and a reason for every suppression).
- **Security tooling:** CodeQL for the Python code and the workflows; zizmor for the workflows; detect-secrets and detect-private-key; Dependabot for Python packages, GitHub Actions and the Docker base image, with a 7-day cooldown; least-privilege workflow permissions and no third-party actions.
- **Developer tooling:** uv with a lockfile; a `Makefile` (`make check`, `make test`, `make run` and more); pre-commit hooks for file hygiene, secrets, ShellCheck, zizmor and the schemas of the GitHub files; EditorConfig.
- **Docker image:** multi-stage build that runs as a non-root user who cannot change the installed code, with a health check and an optional `/data` volume for a DuckDB file that outlives the container.
- **Documentation:** Lesson 3 in `LEARNING.md`; `CONTRIBUTING.md`, `SECURITY.md` and `CODE_OF_CONDUCT.md`; issue and pull request templates; `CODEOWNERS`.

### Changed

- Dependencies are managed with uv, in `backend/pyproject.toml` and `backend/uv.lock`, instead of `requirements.txt` files.

### Fixed

- Duplicate column names after cleaning could still collide (for example a, a and a_1); every column now gets a unique name.
- `make_chart` with an empty `y` column name failed with "Internal error in tool make_chart"; it now tells the agent what to fix.
- A very large tool result was sent to Claude whole. Tool results are now cut at 50,000 characters, with a note that asks the agent to select fewer columns or aggregate.
- The `.env` file and the CLI's input files were read whole, however large; they are now read with a size limit.

[Unreleased]: https://github.com/MITRAKER/ai-data-analyst/commits/main
