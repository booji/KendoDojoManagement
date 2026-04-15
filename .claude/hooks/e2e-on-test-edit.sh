#!/usr/bin/env bash
# PostToolUse hook — auto-run Playwright e2e tests after editing test_e2e_*.py
#
# Behaviour:
#   - Only fires on Edit/Write to backend/tests/test_e2e_*.py
#   - Runs only the edited file (not the full e2e suite)
#   - Detects running servers; starts only what's missing; never tears down
#     servers it didn't start
#   - Silent when all tests pass
#   - On failure: injects the last 50 lines + all screenshot/log paths found
#     in the full output
#   - On server startup failure: injects a clear error and skips tests

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

# Only fire for Edit and Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

# Only fire for test_e2e_*.py files under backend/tests/
BASENAME=$(basename "$FILE_PATH")
if [[ "$BASENAME" != test_e2e_*.py ]] || [[ "$FILE_PATH" != */backend/tests/* ]]; then
  exit 0
fi

# Resolve project root and key dirs from FILE_PATH
# Works for both main project and isolated worktrees
BACKEND_DIR="${FILE_PATH%%/backend/tests/*}/backend"
FRONTEND_DIR="${FILE_PATH%%/backend/tests/*}/frontend"

# ── Helpers ────────────────────────────────────────────────────────────────

inject_error() {
  printf '%s' "$1" | jq -Rs '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: .}}'
  exit 0
}

wait_for_port() {
  local port=$1 label=$2 timeout=20
  for i in $(seq 1 $timeout); do
    curl -sf "http://localhost:${port}" > /dev/null 2>&1 && return 0
    sleep 1
  done
  inject_error "e2e skipped: ${label} failed to become ready on :${port} after ${timeout}s"
}

# ── Guard: venv ─────────────────────────────────────────────────────────────

if [[ ! -f "$BACKEND_DIR/.venv/bin/activate" ]]; then
  inject_error "e2e skipped: no venv found at ${BACKEND_DIR}/.venv"
fi

# ── Start backend if not running ─────────────────────────────────────────────

STARTED_BACKEND=0
if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
  (cd "$BACKEND_DIR" && . .venv/bin/activate && uvicorn app.main:app --port 8000 > /tmp/e2e-hook-backend.log 2>&1) &
  BACKEND_PID=$!
  STARTED_BACKEND=1
  wait_for_port 8000 "backend"
fi

# ── Start frontend dev server if not running ─────────────────────────────────

STARTED_FRONTEND=0
if ! curl -sf http://localhost:5173 > /dev/null 2>&1; then
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    inject_error "e2e skipped: frontend node_modules missing at ${FRONTEND_DIR}"
  fi
  (cd "$FRONTEND_DIR" && npm run dev -- --port 5173 > /tmp/e2e-hook-frontend.log 2>&1) &
  FRONTEND_PID=$!
  STARTED_FRONTEND=1
  wait_for_port 5173 "frontend dev server"
fi

# ── Run only the edited e2e file ─────────────────────────────────────────────

FULL_OUTPUT=$(cd "$BACKEND_DIR" && . .venv/bin/activate && pytest "$FILE_PATH" -q 2>&1)
PYTEST_EXIT=$?

# ── Tear down only servers we started ────────────────────────────────────────

if [[ $STARTED_BACKEND -eq 1 ]]; then
  kill "$BACKEND_PID" 2>/dev/null
fi
if [[ $STARTED_FRONTEND -eq 1 ]]; then
  kill "$FRONTEND_PID" 2>/dev/null
fi

# ── Silent on green ───────────────────────────────────────────────────────────

if [[ $PYTEST_EXIT -eq 0 ]]; then
  exit 0
fi

# ── On failure: last 50 lines + all screenshot/log paths ─────────────────────

TAIL_OUTPUT=$(printf '%s' "$FULL_OUTPUT" | tail -n 50)

# Extract any file paths that look like screenshots or browser logs
ARTIFACT_PATHS=$(printf '%s' "$FULL_OUTPUT" | grep -oE '[^ ]+\.(png|webm|zip|log)' | sort -u | tr '\n' ' ')

CONTEXT="e2e tests FAILED — ${FILE_PATH}

--- last 50 lines ---
${TAIL_OUTPUT}"

if [[ -n "$ARTIFACT_PATHS" ]]; then
  CONTEXT="${CONTEXT}

--- artifact paths ---
${ARTIFACT_PATHS}"
fi

printf '%s' "$CONTEXT" | jq -Rs '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: .}}'
exit 0
