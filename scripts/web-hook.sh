#!/usr/bin/env bash
# Runs one of the web UI's npm scripts for a git hook, for example:
#   scripts/web-hook.sh lint
#
# The npm scripts use the web UI's own tools from frontend/node_modules, at the
# versions in frontend/package-lock.json. Without them, npm would quietly run
# another copy of Prettier or ESLint found elsewhere on this computer, which may
# format differently, or fail with "not found". So this stops with a clear
# message instead.
set -euo pipefail

cd "$(dirname "$0")/../frontend"

if [ ! -x node_modules/.bin/next ]; then
  echo "The web UI's packages are not installed. Run 'make web-setup' first." >&2
  echo "(Or skip the web UI's hooks: SKIP=web-format,web-lint,web-check git ...)" >&2
  exit 1
fi

exec npm run --silent "$1"
