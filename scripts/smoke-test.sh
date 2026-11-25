#!/usr/bin/env bash
# Smoke test for the Docker image. It starts a container from the image, waits
# until Docker's own health check passes, and then uses the app the way a person
# would: it uploads the sample CSV, runs a SQL query and runs Python in the
# sandbox. It also checks two security settings of the image, and that the API
# refuses requests that another website could make a browser send.
#
# CI runs it after building the image. To run it yourself (Docker must be running):
#   make docker smoke
#
# Usage: scripts/smoke-test.sh [IMAGE]    (the default IMAGE is ai-data-analyst)
set -euo pipefail

image="${1:-ai-data-analyst}"
# $$ is the id of this script's process, so two runs never pick the same name.
container="ai-data-analyst-smoke-$$"

# Work from the repository root, wherever the script was started from.
cd "$(dirname "$0")/.."

fail() {
  echo "Smoke test FAILED: $*" >&2
  exit 1
}

# This runs when the script ends, whether it passed or failed. After a failure
# it prints the app's log, to show what went wrong. Then it removes the container.
cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- Log of the container ---" >&2
    docker logs "$container" >&2 || true
  fi
  docker rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting a container from the image $image"
# "127.0.0.1::8000" publishes the app's port 8000 on a free port of this
# computer, which only this computer can reach. "docker port" tells us which.
docker run --detach --name "$container" --publish 127.0.0.1::8000 "$image" >/dev/null
url="http://$(docker port "$container" 8000/tcp | head -n 1)"

echo "Waiting for Docker's health check to pass (at most 90 seconds)"
health="starting"
for _ in $(seq 1 45); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
  if [ "$health" = "healthy" ]; then
    break
  fi
  sleep 2
done
[ "$health" = "healthy" ] || fail "the container is '$health', not 'healthy'"

echo "Checking that the app does not run as root"
uid="$(docker exec "$container" id -u)"
[ "$uid" = "10001" ] || fail "the app runs as user id $uid, not 10001"

echo "Checking that the app cannot change its own code"
if docker exec "$container" touch /app/.venv/smoke-test 2>/dev/null; then
  fail "the app's user can write to /app/.venv"
fi

echo "Uploading the sample dataset"
curl --fail --silent --show-error --form "file=@data/sample_sales.csv" "$url/datasets" >/dev/null

echo "Running a SQL query"
answer="$(curl --fail --silent --show-error --header "Content-Type: application/json" \
  --data '{"sql": "SELECT count(*) AS orders FROM sample_sales"}' "$url/query")"
case "$answer" in
  *'"rows":[[2000]]'*) ;;
  *) fail "expected 2000 orders, got: $answer" ;;
esac

echo "Checking that requests from other websites, or for other host names, are refused"
# A page on another website could make the browser send this upload, and the
# browser names that site in the Origin and Sec-Fetch-Site headers.
code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Origin: https://evil.example" --header "Sec-Fetch-Site: cross-site" \
  --form "file=@data/sample_sales.csv;filename=planted.csv" "$url/datasets")"
[ "$code" = "403" ] || fail "an upload from another website got HTTP $code, not 403"
# DNS rebinding: another website's name, pointed at this computer.
code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Host: evil.example" "$url/datasets")"
[ "$code" = "421" ] || fail "a request for another host name got HTTP $code, not 421"

echo "Running Python in the sandbox"
printed="$(docker exec "$container" python -c '
import pandas as pd
from app.agent.sandbox import run_python

result = run_python("print(df.n.sum())", pd.DataFrame({"n": [1, 2, 3]}))
print(result.stdout if result.ok else result.error, end="")
')"
[ "$printed" = "6" ] || fail "the sandbox printed '$printed', not 6"

echo "Smoke test passed."
