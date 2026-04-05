#!/usr/bin/env bash
# PostToolUse hook — auto-run pytest after editing backend/app/**/*.py
#
# Behaviour:
#   - Silent (no output) when all tests pass
#   - Injects full pytest output as additionalContext when tests fail
#   - Injects a warning when the venv is missing
#   - Works in both the main project and isolated worktrees

INPUT=$(cat)

# Extract fields
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

# Only fire for Edit and Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

# Only fire for .py files under backend/app/
if [[ "$FILE_PATH" != *.py ]] || [[ "$FILE_PATH" != */backend/app/* ]]; then
  exit 0
fi

# Resolve backend/ root — works for both main project and worktrees
BACKEND_DIR="${FILE_PATH%%/backend/app/*}/backend"

# Warn if venv is missing
if [[ ! -f "$BACKEND_DIR/.venv/bin/activate" ]]; then
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"pytest skipped: no venv found at %s/.venv"}}\n' "$BACKEND_DIR"
  exit 0
fi

# Run unit tests (exclude slow e2e tests)
OUTPUT=$(cd "$BACKEND_DIR" && . .venv/bin/activate && pytest -q --ignore-glob="tests/test_e2e_*.py" 2>&1)
PYTEST_EXIT=$?

if [[ $PYTEST_EXIT -eq 0 ]]; then
  # Silent on green — no output injected
  exit 0
fi

# Tests failed — inject full output so the agent can act on it immediately
# Use stdin to avoid "argument list too long" on large pytest output
printf '%s' "$OUTPUT" | jq -Rs '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: .}}'
exit 0
