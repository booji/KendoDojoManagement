---
name: implement
description: Orchestrator skill for KendoDojoManagement. Spawns specialised subagents (TDD, backend, frontend, QA, security) in sequence using the Agent tool to implement a GitHub issue end-to-end. Use when given an issue number to implement (e.g. "implement issue 6", "/implement 3"), or when the user wants to work through a full vertical slice from DB to UI.
---

# Implement — Orchestrator

Implements a GitHub issue end-to-end by spawning specialised subagents in the correct order.
All subagents run on the **sonnet** model. On any agent failure: retry once with the error as context. If it fails again, stop and escalate to the user with both error outputs and your hypothesis about why.

---

## Step 1 — Read the issue and create a branch

```bash
gh issue view <number>
gh issue view 1   # PRD for full context
```

Read both before touching any code. Extract **acceptance criteria** as a numbered list — these drive the TDD agent.

Then create and switch to a feature branch:
```bash
git checkout -b feat/issue-<number>
```

All subsequent work (by you and all subagents) happens on this branch. Never commit to `main` directly.

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

Lint on the host, from backend/ with the venv active (. .venv/bin/activate):
  ruff check . --fix
  ruff format .

Tests run in a container, from the repo root. Podman is the supported
runtime (`docker compose` works only with the podman-docker shim). Bare
pytest on the host raises a RuntimeError in conftest.py (it requires a
PostgreSQL DATABASE_URL):
  podman-compose -f docker-compose.test.yml run --rm test

Never start uvicorn or npm run dev yourself — the container entrypoint
(run_tests.sh) starts both servers before invoking pytest. Running one in the
foreground will hang until it times out.

Both must pass with zero errors. Report the pytest output.
Do not weaken or delete a test to make it pass. If a test encodes a wrong
expectation, stop and report it rather than editing it.
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

Read the skill at .claude/skills/tdd/SKILL.md for all rules and conventions, especially the Playwright section and the xfail lifecycle.

## NEVER start servers yourself

Do NOT run `uvicorn` or `npm run dev`. The test container's entrypoint
(`backend/run_tests.sh`) already starts uvicorn (:8000) and Vite (:5173) and
waits for both before invoking pytest. Starting them by hand in the foreground
hangs your turn until it times out, which has burned entire agent runs.

Bare `pytest` on the host also does not work: `backend/tests/conftest.py`
raises unless `DATABASE_URL` is a PostgreSQL URL naming a "test" database.

## Step 1 — Run the full suite

From the repo root. A full run takes ~11 minutes.
```bash
podman-compose -f docker-compose.test.yml run --rm test \
  > /tmp/suite.log 2>&1; echo "exit=$?"
grep -aE "short test summary|[0-9]+ passed" /tmp/suite.log | tail -5
```

Redirect to a file. Do NOT pipe the run through `tail` — the summary line is
the one thing you need and it is trivially truncated away.

Do NOT pass `--entrypoint bash`. That skips `run_tests.sh`, so no servers start
and every `test_e2e_*` test fails with connection-refused. That looks like a
catastrophic regression and is only a misconfigured run.

To scope a run to one file, keep the entrypoint and use `PYTEST_TARGET`.
Pytest flags go through `PYTEST_ARGS` — trailing arguments after the service
name become the container command under `podman-compose`, not pytest flags:
```bash
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_e2e_foo.py -e PYTEST_ARGS=-x test
```

## Step 2 — Promote xfail stubs

For each file matching `backend/tests/test_e2e_*.py`:
1. Read the file.
2. For every test still marked `@pytest.mark.xfail`: decide first whether the
   acceptance criterion is genuinely verifiable through a browser. State your
   reasoning explicitly.
3. If yes, replace the stub body with real Playwright assertions against the
   live UI at http://localhost:5173, then re-run (step 1) to verify.

**Judgement required — a stub is not automatically promotable.** Criteria about
HTTP response indistinguishability, DB state, or raw bytes are better asserted
at the HTTP layer than through a browser. A WebAuthn ceremony in particular
cannot complete in headless Chromium without a virtual authenticator.

If a criterion cannot be meaningfully verified in a browser, do NOT fake it and
do NOT leave a strict xfail that will break CI once behaviour changes. Report
why, and recommend either converting it to an HTTP-level test in the non-e2e
suite or what setup a real browser test would require. Never promote a stub
into an assertion that passes without actually verifying the criterion.

## Step 3 — Investigate every failure before reporting it

A failing test is not automatically a regression. Re-run failures in isolation
(`PYTEST_TARGET`) — the suite has known contention flakiness under a full run.
Report whether each failure reproduces in isolation, and whether it touches
code this issue changed. Say plainly when you have not confirmed a failure
against `main`.

## Report
- Exact suite counts, and the command you actually ran
- Which xfail stubs were promoted, what assertions were added, and whether you
  ran them
- Any stub you declined to promote, and why
- For each failure: reproduces in isolation? related to this diff?
- Confirm no stray processes or throwaway files remain

Honesty beats a green checkmark. If any test fails, do NOT mark the work done.
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

Tell the user to push the branch:
```
Please run: ! git push origin feat/issue-<number>
Then I will open the PR.
```

Wait for confirmation, then open the PR:
```bash
gh pr create \
  --base main \
  --head feat/issue-<number> \
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
