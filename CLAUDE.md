# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

KendoDojoManagement — manages sessions and members of a kendo dojo. Open source, self-hosted, single-dojo-per-instance.

## Stack

- **Backend:** Python + FastAPI
- **Frontend:** React + Vite + shadcn/ui
- **Database:** PostgreSQL (prod), SQLite (dev/test) via SQLAlchemy
- **Auth:** Passkeys/WebAuthn (`py_webauthn`) primary; email/password fallback
- **API:** REST
- **Deployment:** Docker Compose (app + PostgreSQL containers)
- **Primary keys:** UUID

## Type Configuration Convention

Any domain "type" (e.g. session type, grading, shogo, officer roles, membership type) must be configurable exclusively through Admin Settings. Never add inline type creation to feature dialogs or forms — all type management belongs in the admin settings page.

Planned future types: Grading, Shogo, Officer Roles, Membership Type.

## UI Conventions

### Desktop Layout
Pages use full-width layout with `px-4` padding. No `max-w-*` constraint on page wrappers — content fills the available space beside the sidebar. Use responsive grid (`md:grid-cols-2`, `md:grid-cols-4` etc.) to structure content on wider screens rather than capping width.

### Button Ordering (macOS HIG)
Action buttons are right-aligned (`justify-end`). Order left-to-right: most destructive → least destructive → primary/safe action. Example: `Cancel Series` | `Cancel Session` | `Edit`. The default/safe action always sits rightmost.

## Design Philosophy

**Deep modules** (Ousterhout, *A Philosophy of Software Design*): favor small interfaces hiding large implementations. A caller should need to know as little as possible about what's underneath. New modules and abstractions should earn their existence by hiding meaningful complexity.

Abstraction is encouraged where it genuinely aids human readability; avoid speculative abstractions for hypothetical future needs.

## TDD Workflow

Follow red-green as **vertical slices**, not horizontal slicing:
1. Write one failing test for the next small behavior.
2. Write the minimum implementation to make it pass.
3. Refactor if needed, then move to the next test.

Never write a full test suite first and then implement everything — that is horizontal slicing and is explicitly not the workflow here.

## Security

Apply security best practices at all system boundaries:
- Validate and sanitize all external input.
- Never hardcode secrets; use environment variables or a secrets manager.
- Apply least-privilege principles to auth and data access.
- Use parameterized queries / ORM-level protections against injection.

## Build / Test / Lint

All backend commands run from `backend/` with the venv active (`. .venv/bin/activate`):

```bash
# Backend
cd backend
. .venv/bin/activate
pytest                  # run tests
ruff check .            # lint
ruff format .           # format
uvicorn app.main:app --reload  # dev server

# Frontend
cd frontend
npm run dev             # dev server
npm run build           # production build
```
