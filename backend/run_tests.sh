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
exec pytest tests/ -x -q "$@"
