# Container image for the AI Data Analyst backend (the FastAPI app).
#
# Build it from the repository root. The build context is the backend/ folder:
#   docker build -t ai-data-analyst backend
# Run it. "-e ANTHROPIC_API_KEY" copies the key from your shell into the
# container at run time, so the key is never stored inside the image:
#   docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY ai-data-analyst
# Then check it: curl http://localhost:8000/health
#
# By default the data lives in memory and is gone when the container stops. To
# keep it, store the DuckDB file in a named volume mounted at /data:
#   docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY \
#     -e DUCKDB_PATH=/data/analyst.duckdb -v analyst-data:/data ai-data-analyst
#
# This is a multi-stage build. Stage 1 ("builder") installs the app and its
# dependencies into a virtual environment. Stage 2 starts again from a clean
# image and copies in only that finished environment. Build tools such as uv
# stay behind in stage 1, so the image we ship is smaller and has less in it
# that an attacker could use.

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.15-slim AS builder

# Install uv, our package manager. The exact version is pinned (the same one
# CI uses), so every build behaves the same. --no-cache-dir keeps pip's
# download cache out of the image.
RUN pip install --no-cache-dir uv==0.13.8

# Settings for uv:
#   UV_COMPILE_BYTECODE=1      compile .py files to .pyc now, so the app starts faster
#   UV_LINK_MODE=copy          copy files into the venv instead of linking to uv's cache
#   UV_PYTHON_DOWNLOADS=never  use the Python 3.15 in this image, never download one
#   UV_PROJECT_ENVIRONMENT     where uv creates the virtual environment ("venv")
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install the dependencies first, using only the two files that list them.
# Docker caches the result of each step. While pyproject.toml and uv.lock stay
# the same, later builds reuse this slow step, even when our code changes.
#   --locked              stop with an error if uv.lock does not match pyproject.toml
#   --no-dev              skip developer tools (pytest, ruff, mypy and so on)
#   --no-install-project  install only the dependencies; our code is not copied yet
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Now copy our code and install the app package itself into the venv.
# --no-editable installs a real copy of the package into the venv, not a link
# back to /app/app. That is why the final stage needs only the venv and not
# the source folder.
COPY app ./app
RUN uv sync --locked --no-dev --no-editable

# ---------------------------------------------------------------------------
# Stage 2: the final image
# ---------------------------------------------------------------------------
# Use the same base image as the builder: the venv expects this exact Python.
FROM python:3.15-slim

# Labels describe the image to registries and tools. These are the standard
# OCI names. The "source" label links the image on ghcr.io to this repository.
LABEL org.opencontainers.image.title="AI Data Analyst" \
      org.opencontainers.image.description="AI Data Analyst backend: upload a CSV, ask questions in plain English, and an AI agent answers using SQL, Python and charts." \
      org.opencontainers.image.source="https://github.com/MITRAKER/ai-data-analyst" \
      org.opencontainers.image.licenses="MIT"

# Create an ordinary user to run the app, so it does not run as root. If an
# attacker ever got in through the app, they would have very few rights.
#   --gid / --uid 10001       a fixed, high id that no other account uses
#   --no-create-home          this account needs no home folder
#   --no-log-init             skip the login records (a high uid can make them huge)
#   --shell /usr/sbin/nologin nobody can log in as this user
# /data is the one folder this user may write to, for a DuckDB file that should
# outlive the container (see the top of this file). A new named volume mounted
# there copies this owner, so the app can write to it too.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --no-log-init \
       --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data

WORKDIR /app

# Copy the finished venv from the builder stage. It holds the app package and
# all of its dependencies. Nothing else from stage 1 comes along. The files stay
# owned by root, so the "app" user can run the code but cannot change it.
COPY --from=builder /app/.venv /app/.venv

# PATH: look in the venv first, so "python" and "uvicorn" mean the venv's copies.
# PYTHONUNBUFFERED=1: print log lines at once, so "docker logs" shows them live.
# PYTHONDONTWRITEBYTECODE=1: do not write .pyc files while running (stage 1
# already compiled them).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# From here on, everything runs as the "app" user.
USER app

# Document that the app listens on port 8000. "docker run -p 8000:8000" is what
# actually opens the port to your machine.
EXPOSE 8000

# Every 30 seconds, Docker checks that the app still answers GET /health. After
# 3 failed checks in a row, Docker marks the container "unhealthy". The slim
# image has no curl, so the check uses Python's built-in urllib. Any error, or
# a reply that is not 2xx, makes the command fail. ProxyHandler({}) makes urllib
# ignore proxy settings, so the check always talks to the app directly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request as r; r.build_opener(r.ProxyHandler({})).open('http://127.0.0.1:8000/health', timeout=4)"]

# Start the web server. Host 0.0.0.0 means "accept connections on every network
# interface". Inside a container that is required, or requests from outside the
# container could not reach the app.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
