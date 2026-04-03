---
name: implement
description: Orchestrator skill for KendoDojoManagement. Spawns specialised subagents (TDD, backend, frontend, QA, security) in sequence using the Agent tool to implement a GitHub issue end-to-end. Use when given an issue number to implement (e.g. "implement issue 6", "/implement 3"), or when the user wants to work through a full vertical slice from DB to UI.
---

# Implement — Orchestrator

Implements a GitHub issue end-to-end by spawning specialised subagents in the correct order.
All subagents run on the **sonnet** model. On any agent failure: retry once with the error as context. If it fails again, stop and escalate to the user with both error outputs and your hypothesis about why.

---

## Step 1 — Read the issue

```bash
gh issue view <number>
gh issue view 1   # PRD for full context
```

Read both before spawning any agent. Extract **acceptance criteria** as a numbered list — these drive the TDD agent.

---

## Step 2 — Spawn the TDD agent (RED phase)

Use the Agent tool:
```
subagent_type: general-purpose
model: sonnet
isolation: worktree
```

Prompt template:
```
You are the TDD agent for KendoDojoManagement.

Read the skill at .claude/skills/tdd/SKILL.md for all rules and conventions.

Your job: write FAILING tests only. Do not implement anything.

Acceptance criteria for issue #<number>:
<paste numbered list>

Write:
1. Unit/integration tests in backend/tests/test_<concept>.py using pytest + StubRepository
2. One Playwright browser test stub per acceptance criterion in backend/tests/test_e2e_<concept>.py marked xfail(strict=True)

Confirm all new tests fail before finishing. Report which tests you wrote and their failure output.
```

Wait for the TDD agent to complete. If tests do not fail (they pass or error unexpectedly), retry once. If still wrong, escalate.

---

## Step 3 — Spawn the Backend agent (GREEN phase)

Use the Agent tool:
```
subagent_type: general-purpose
model: sonnet
isolation: worktree
```

Prompt template:
```
You are the Backend agent for KendoDojoManagement.

Read the skill at .claude/skills/backend/SKILL.md for all rules and conventions.

Issue #<number> has been partially implemented: failing tests exist in backend/tests/.
Your job: implement the minimum backend code to make those tests pass.

Follow the pattern: model → repository → router → register in main.py
After implementation run from backend/ with venv active (. .venv/bin/activate):
  ruff check . --fix
  pytest -q

Both must pass with zero errors. Report the pytest output.
If a model changed, remind the user to run Alembic migrations.
```

Wait for backend agent. On failure retry once, then escalate.

---

## Step 4 — Spawn the Frontend agent (if UI is needed)

Only spawn if the issue requires frontend changes. Check the issue description.

Use the Agent tool:
```
subagent_type: general-purpose
model: sonnet
isolation: worktree
```

Prompt template:
```
You are the Frontend agent for KendoDojoManagement.

Read the skill at .claude/skills/frontend/SKILL.md for all rules and conventions.

The backend API for issue #<number> is now implemented. Your job: build the UI.

API contract (routes + schemas defined in the backend):
<paste relevant route paths and Pydantic schema shapes>

After implementation run from frontend/:
  npm run build

Must pass with zero TypeScript errors. Report the build output.
```

Wait for frontend agent. On failure retry once, then escalate.

---

## Step 5 — Spawn QA agent and Security agent IN PARALLEL

Fire both Agent tool calls in the same message.

### QA agent prompt:
```
You are the QA agent for KendoDojoManagement.

Read the skill at .claude/skills/tdd/SKILL.md for all rules and conventions, especially the Playwright section.

Both servers are running:
  - Backend: http://localhost:8000
  - Frontend: http://localhost:5173

Your job:
1. Run all unit/integration tests: cd backend && . .venv/bin/activate && pytest -q
2. Run all Playwright browser tests: pytest backend/tests/test_e2e_*.py --headed=false -q
3. Remove xfail markers from any browser tests that now pass

Report full pytest output. If any test fails, report the failure and do NOT mark the work as done.
```

### Security agent prompt:
```
You are the Security agent for KendoDojoManagement.

Read the skill at .claude/skills/security/SKILL.md for the full checklist and severity levels.

Review all files changed in this branch for issue #<number>.
Use: git diff main --name-only

Apply every checklist item relevant to the changed files.
Report findings using CRITICAL / WARNING / INFO severity levels.
Do NOT modify any files — report only.
If there are CRITICAL findings, the issue cannot be marked done.
```

Wait for both. Collect all findings.

---

## Step 6 — Evaluate and report

### Terminal summary (always print this):

```
## Issue #<number> — Implementation Report

### Pipeline result
- TDD (red):     PASS / FAIL
- Backend:       PASS / FAIL
- Frontend:      PASS / FAIL (or N/A)
- QA (pytest):   PASS / FAIL  — <X> tests, <Y> passed
- QA (e2e):      PASS / FAIL  — <X> tests, <Y> passed
- Security:      CLEAR / FINDINGS

### Security findings
<list or "None">

### Open items
<any follow-up issues needed, Alembic migration reminder if models changed>
```

### Open a PR (always, even if there are findings):

```bash
gh pr create \
  --title "feat: <brief description> (#<number>)" \
  --body "$(cat <<'EOF'
## Issue
Closes #<number>

## What was built
<bullet list of files created/changed>

## Test results
- pytest: <X> passed
- e2e (Playwright): <X> passed

## Security review
<CLEAR or list of findings by severity>

## Open items
<follow-up issues, migration reminders>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Hard rules
- TDD always: failing tests before any implementation
- Never start frontend until backend routes + schemas are tested
- Never mark done if `pytest` or `npm run build` is failing
- Never mark done if there are CRITICAL security findings
- Never hardcode secrets — all config via env vars
- One retry per failing agent, then escalate to the user
