---
name: implement
description: Orchestrator skill for KendoDojoManagement. Implements a GitHub issue end-to-end by coordinating backend, frontend, TDD, and security concerns in the correct order. Use when given an issue number to implement (e.g. "implement issue 6", "/implement 3"), or when the user wants to work through a full vertical slice from DB to UI.
---

# Implement

Implements a GitHub issue end-to-end. Coordinates all layers in the right order.

## Workflow

### 1. Understand the issue
```
gh issue view <number>
gh issue view 1   # PRD for full context
```
Read both before touching any code.

### 2. Explore the codebase
Check current state of relevant files. Do not assume — read what exists.

### 3. Plan
Decide which layers are affected:
- New domain module? → follow `/new-slice` pattern (see `skills/new-slice/PATTERNS.md`)
- Backend only? → follow `/backend` rules
- Frontend only? → follow `/frontend` rules
- Both? → define API contract (routes + Pydantic schemas) first, then implement backend, then frontend

### 4. Implement — in this order

- [ ] Write failing test(s) first (`/tdd` rules)
- [ ] Implement backend (model → repo → router → register in `main.py`)
- [ ] Run backend gates: `.venv/bin/ruff check . --fix` + `.venv/bin/pytest -q`
- [ ] If frontend needed: implement UI against the confirmed API contract
- [ ] Run frontend gate: `npm run build` (zero TS errors)

### 5. Security review
Apply the `/security` checklist to all changed files.
If the issue touches auth or stores/reads PII: security review is **mandatory**.

### 6. Close the loop
Report:
- What was built (files created/changed)
- Test results
- Any open questions or follow-on issues needed
- Alembic migration reminder if models changed

## Hard rules
- TDD always: failing test before implementation, never the other way
- Never start frontend until routes + schemas are defined and tested
- Never finish if `pytest` or `npm run build` is failing
- Never hardcode secrets — all config via env vars
