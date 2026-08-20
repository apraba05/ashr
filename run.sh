#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REDIS_PORT="${REDIS_PORT:-6389}"
CONTAINER="agent-regression-gate-redis"
AGENT_IMAGE="ashr-agent-regression-runner"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$ROOT"
cleanup
docker build --quiet -f Dockerfile.agent -t "$AGENT_IMAGE" . >/dev/null
docker run --rm -d --name "$CONTAINER" -p "$REDIS_PORT:6379" redis:7-alpine >/dev/null
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER" redis-cli ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$CONTAINER" redis-cli ping >/dev/null

go build -o .tmp/evaldiff ./cmd/evaldiff

run_agent() {
  docker run --rm \
    --network "container:$CONTAINER" \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$ROOT:/app" \
    -w /app \
    "$AGENT_IMAGE" python agent/runner.py "$@"
}

rm -rf current

echo "== Record frozen golden baselines =="
run_agent record

echo
echo "== Unchanged agent: should pass =="
run_agent run --prompt-version baseline --output current
.tmp/evaldiff -redis "localhost:$REDIS_PORT" -current current

echo
echo "== One-line prompt regression: CI should catch it =="
run_agent run --prompt-version regressed --output current
if .tmp/evaldiff -redis "localhost:$REDIS_PORT" -current current; then
  echo "ERROR: deliberate regression was not detected"
  exit 1
fi

echo
echo "Demo complete: the expected regression was blocked."
