#!/usr/bin/env bash
# Starts backend + frontend servers, then runs the full test suite.
# Used as the entrypoint for docker-compose.test.yml.
set -euo pipefail

# Install frontend dependencies
cd /frontend
npm ci --prefer-offline

# Start backend API server
cd /app
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start Vite dev server
cd /frontend
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

cleanup() { kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo "Waiting for backend on :8000..."
for i in $(seq 1 30); do
    curl -sf http://localhost:8000/health >/dev/null && break
    sleep 1
done

echo "Waiting for frontend on :5173..."
for i in $(seq 1 30); do
    curl -sf http://localhost:5173 >/dev/null && break
    sleep 1
done

echo "Both servers ready — running tests"
cd /app
# No -x: a full run reports on the whole suite, so a passing run is evidence
# and a failing run names every problem at once (see #221). Fail-fast is still
# available on demand — the script forwards "$@", so pass -x explicitly to
# stop at the first failure while iterating.
#
# PYTEST_TARGET overrides which paths are collected (default: the whole suite),
# so a single file can be exercised without editing this script, e.g.
#   docker compose -f docker-compose.test.yml run --rm \
#     -e PYTEST_TARGET=tests/test_e2e_settings.py test
exec pytest ${PYTEST_TARGET:-tests/} -q "$@"
