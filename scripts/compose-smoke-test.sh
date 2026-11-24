#!/usr/bin/env bash
# Smoke test for Docker Compose (compose.yaml). It builds and starts both
# services, waits until their health checks pass, and then uses the app through
# the web UI's server, the way the browser does. It also checks the security
# settings: what can be reached from outside, which user each app runs as, and
# where the apps may write.
#
# It runs without a Claude API key, so it never calls Claude and costs nothing.
#
# CI runs it in the "Docker Compose" job. To run it yourself (Docker must be running):
#   make compose-smoke
set -euo pipefail

# Work from the repository root, wherever the script was started from.
cd "$(dirname "$0")/.."

# A project name of its own, so the test never touches the containers or the
# data of your own `docker compose up`. $$ (this script's process id) makes it
# unique.
project="ai-data-analyst-smoke-$$"
big_file="$(mktemp)"

compose() {
  docker compose --project-name "$project" "$@"
}

fail() {
  echo "Compose smoke test FAILED: $*" >&2
  exit 1
}

# This runs when the script ends, whether it passed or failed. After a failure
# it prints the logs of both services. Then it removes the containers, their
# network and the test's data volume.
cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- Logs of the services ---" >&2
    compose logs --no-color >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$big_file"
}
trap cleanup EXIT

# Settings in the shell win over a .env file, so this run has no API key even
# if your .env has one. An empty WEB_PORT publishes the web UI on a free port.
export ANTHROPIC_API_KEY="" WEB_PORT=""

start() {
  compose up --detach --wait --wait-timeout 180
  url="http://$(compose port web 3000)"
}

echo "Building and starting both services, and waiting for their health checks"
compose build
start

echo "Checking the page and its security headers"
headers="$(curl --fail --silent --show-error --dump-header - --output /dev/null "$url/")"
for header in "x-frame-options: DENY" "x-content-type-options: nosniff" \
  "content-security-policy: default-src 'self';"; do
  grep --quiet --ignore-case --fixed-strings "$header" <<<"$headers" ||
    fail "the page has no '$header' header"
done
grep --quiet --ignore-case --extended-regexp \
  "^content-security-policy: .*script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'" \
  <<<"$headers" || fail "the page's Content-Security-Policy has no nonce"

echo "Uploading the sample dataset through the web UI's server"
answer="$(curl --fail --silent --show-error --form "file=@data/sample_sales.csv" "$url/api/datasets")"
case "$answer" in
  *'"row_count":2000'*) ;;
  *) fail "expected 2000 rows, got: $answer" ;;
esac

echo "Uploading a 20 MB file, to check that large uploads get through"
awk 'BEGIN { print "id,amount,note"; for (i = 0; i < 900000; i++) print i "," i % 977 ",abcdefghij" }' \
  >"$big_file"
answer="$(curl --fail --silent --show-error --form "file=@$big_file;filename=big.csv" "$url/api/datasets")"
case "$answer" in
  *'"row_count":900000'*) ;;
  *) fail "expected 900000 rows, got: $answer" ;;
esac

echo "Checking that a file over 50 MB is refused before it reaches the API"
head --bytes 53000000 /dev/zero >"$big_file"
code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --form "file=@$big_file;filename=huge.csv" "$url/api/datasets")"
[ "$code" = "413" ] || fail "a 53 MB upload got HTTP $code, not 413"

echo "Listing the datasets, and reading one"
answer="$(curl --fail --silent --show-error "$url/api/datasets")"
case "$answer" in
  *'"sample_sales"'*) ;;
  *) fail "sample_sales is not in the list: $answer" ;;
esac
answer="$(curl --fail --silent --show-error "$url/api/datasets/sample_sales")"
case "$answer" in
  *'"name":"order_date","type":"TIMESTAMP"'*) ;;
  *) fail "unexpected details of sample_sales: $answer" ;;
esac

echo "Checking that the agent reports the missing API key"
answer="$(curl --fail --silent --show-error "$url/api/agent/status")"
case "$answer" in
  *'"ready":false'*'ANTHROPIC_API_KEY'*) ;;
  *) fail "unexpected agent status: $answer" ;;
esac
code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Content-Type: application/json" --data '{"question": "Which region sold most?"}' \
  "$url/api/ask")"
[ "$code" = "503" ] || fail "a question without an API key got HTTP $code, not 503"

echo "Checking that the API publishes no port"
# For a port that is not published, "docker compose port" prints ":0".
published="$(compose port api 8000 2>/dev/null || true)"
case "$published" in
  "" | ":0") ;;
  *) fail "the API can be reached from outside Compose, at $published" ;;
esac

echo "Checking that neither app runs as root"
uid="$(compose exec -T web id -u)"
[ "$uid" = "1000" ] || fail "the web UI runs as user id $uid, not 1000"
uid="$(compose exec -T api id -u)"
[ "$uid" = "10001" ] || fail "the API runs as user id $uid, not 10001"

echo "Checking that neither app can change its files"
if compose exec -T web touch /app/server.js 2>/dev/null; then
  fail "the web UI can change its own code"
fi
if compose exec -T web touch /tmp/smoke-test 2>/dev/null; then
  fail "the web UI's file system is not read-only"
fi
if compose exec -T api touch /app/.venv/smoke-test 2>/dev/null; then
  fail "the API can change its own code"
fi

echo "Running Python in the sandbox, in the read-only API container"
printed="$(compose exec -T api python -c '
import pandas as pd
from app.agent.sandbox import run_python

result = run_python("print(df.n.sum())", pd.DataFrame({"n": [1, 2, 3]}))
print(result.stdout if result.ok else result.error, end="")
')"
[ "$printed" = "6" ] || fail "the sandbox printed '$printed', not 6"

echo "Restarting both services, to check that the data is kept"
compose down
start
answer="$(curl --fail --silent --show-error "$url/api/datasets")"
case "$answer" in
  *'"sample_sales"'*) ;;
  *) fail "sample_sales is gone after a restart: $answer" ;;
esac

echo "Compose smoke test passed."
