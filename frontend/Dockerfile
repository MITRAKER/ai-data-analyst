# Container image for the AI Data Analyst web UI (the Next.js app).
#
# Docker Compose builds and starts it together with the API (see compose.yaml
# in the repository root):
#   docker compose up --build
# To build only this image, from the repository root:
#   docker build -t ai-data-analyst-web frontend
#
# The image needs one setting: BACKEND_URL, the address of the Python API
# (http://api:8000 in Compose). The browser never talks to the API itself.
# The API answers only to localhost and the names in its own ALLOWED_HOSTS, so
# add the host name of BACKEND_URL there (Compose adds "api").
# ALLOWED_HOSTS lists more host names that the web UI answers to, besides
# localhost, 127.0.0.1 and [::1] (see SECURITY.md).
#
# This is a multi-stage build, like the backend's. Stage 1 installs the
# packages, stage 2 builds the app, and the final stage gets only the built
# app: Next.js's "standalone" output, a small server.js with just the parts of
# node_modules that it uses. Compilers, tests and dev tools stay behind.

# ---------------------------------------------------------------------------
# Stage 1: install the exact versions in package-lock.json
# ---------------------------------------------------------------------------
FROM node:26-slim AS deps

WORKDIR /app

# Only the files that list the packages, so Docker can reuse this slow step
# while they stay the same. .npmrc turns off install scripts: packages get no
# chance to run code while they are installed.
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit

# ---------------------------------------------------------------------------
# Stage 2: build the app
# ---------------------------------------------------------------------------
FROM node:26-slim AS builder

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 3: the final image
# ---------------------------------------------------------------------------
FROM node:26-slim

LABEL org.opencontainers.image.title="AI Data Analyst web UI" \
      org.opencontainers.image.description="The chat interface of AI Data Analyst: upload a CSV, ask a question, and watch the agent work." \
      org.opencontainers.image.source="https://github.com/MITRAKER/ai-data-analyst" \
      org.opencontainers.image.licenses="MIT"

# NODE_ENV=production: run React and Next.js without their slower dev checks.
# HOSTNAME=0.0.0.0: accept connections from outside the container.
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# The standalone server, and the browser files (JavaScript and CSS) that it
# serves from .next/static. The files stay owned by root, so the user that
# runs the app can read them but cannot change them.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# The app needs Node.js, but not npm. Remove npm, so that nobody can misuse it
# and its own dependencies don't show up in security scans of the image.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

# Run as "node", the ordinary user that the official Node.js images include.
USER node

EXPOSE 3000

# Every 30 seconds, Docker checks that the server still answers. /api/health
# does not call the API, so this checks only this container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]

CMD ["node", "server.js"]
