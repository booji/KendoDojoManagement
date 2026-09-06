# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

KendoDojoManagement — manages sessions and members of a kendo dojo. Open source, self-hosted, single-dojo-per-instance.

## Stack

- **Backend:** Python + FastAPI
- **Frontend:** React + Vite + shadcn/ui
- **Database:** PostgreSQL (dev, test, prod) via SQLAlchemy
- **Auth:** Passkeys/WebAuthn (`py_webauthn`) primary; email/password fallback
- **API:** REST
- **Deployment:** rootless Podman — Quadlet units (`deploy/quadlet`) for the hardened deployment, Compose (app + PostgreSQL containers) for a quick self-host
- **Primary keys:** UUID

## Type Configuration Convention

Any domain "type" (e.g. session type, grading, shogo, officer roles, membership type) must be configurable exclusively through Admin Settings. Never add inline type creation to feature dialogs or forms — all type management belongs in the admin settings page.

Planned future types: Grading, Shogo, Officer Roles, Membership Type.

## UI Conventions

### Desktop Layout
Pages use full-width layout with `px-4` padding. No `max-w-*` constraint on page wrappers — content fills the available space beside the sidebar. Use responsive grid (`md:grid-cols-2`, `md:grid-cols-4` etc.) to structure content on wider screens rather than capping width.

### Copy to Clipboard
Clipboard copying goes through `frontend/src/components/CopyButton.tsx` — do
not hand-roll `navigator.clipboard.writeText` with its own `copied` state. Four
pages predate the component and still do (issue #367); if you are editing one
of them anyway, migrate it.

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

## Database Migrations

Alembic is the single source of truth for the schema. `Base.metadata.create_all`
is not a deployment path — schema changes flow exclusively through the
migration chain.

### Reversals must justify themselves

A migration that **reverses an earlier migration** — adding back an object a
previous revision dropped, or dropping one a previous revision added — must
explain why in its module docstring: what changed, and what supersedes the
earlier decision. A summary line alone is not enough.

This is enforced by `backend/tests/test_migration_conventions.py`, which walks
the revision chain statically (no database) and fails naming the offending
revision, the object, and the revision being reversed.
`a5b6c7d8e9f0_drop_federation_number_from_members.py` is the reference example
of the expected shape.

The convention exists because `members.federation_number` was dropped as
superseded, silently re-added one revision later with no stated reason, and
then sat orphaned in the schema for roughly three months (issue #299).

Revisions predating the convention are listed in `GRANDFATHERED_REVISIONS` in
that test. That list must only ever shrink — new reversals write a docstring
instead.

## Build / Test / Lint

### Container runtime

**Podman is the supported, tested runtime.** Docker is best-effort and
unverified — the Compose files and the Makefile's runtime auto-detection are
expected to work under it, but nothing here is tested against Docker and no
parity is promised. Commands below lead with `podman-compose` / `podman`.

If you have the `podman-docker` shim installed, `docker` and `docker compose`
are aliases and every command works unchanged. A clean Podman install has no
`docker` binary, so the `podman-compose` form is the one written out.

### Tests — always in a container

Tests run in a container, never on the host. `backend/tests/conftest.py` refuses
to collect unless `DATABASE_URL` is a PostgreSQL URL naming a database whose name
contains "test", so a bare `pytest` fails at import with a `RuntimeError` before
a single test runs. Run from the repo root:

```bash
# Full suite (backend + e2e)
podman-compose -f docker-compose.test.yml run --rm test

# A single file or directory
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_members.py test

# Extra pytest flags, e.g. fail-fast while iterating
podman-compose -f docker-compose.test.yml run --rm -e PYTEST_ARGS=-x test
```

```bash
# Backend only — no frontend install, no Vite, no e2e collection (~1 minute)
podman-compose -f docker-compose.test.yml run --rm test-backend
```

The `test-backend` service is the same `run_tests.sh` with `BACKEND_ONLY=1`,
built from the lighter `backend-dev-deps` stage. CI runs it on every push
(`.github/workflows/backend-tests.yml`, advisory); the full suite stays on
release-candidate tags. It cannot catch an e2e regression — run the full suite
before opening a PR.

Pass pytest flags via `PYTEST_ARGS`, **not** positionally after the service
name. `podman-compose` treats trailing arguments as the container command, so
`run --rm test -x` fails with ``crun: executable file `-x` not found in $PATH``;
only real `docker compose` forwards them. `PYTEST_ARGS` works on both runtimes.
It interpolates unquoted (as `PYTEST_TARGET` already did), so keep values free
of `*`, `?` and `[]` — the shell would glob-expand them against `/app`.

The compose service's entrypoint is `backend/run_tests.sh`, which installs
frontend deps and starts uvicorn (:8000) and Vite (:5173) *before* invoking
pytest. The Playwright e2e tests drive those servers.

**Do not pass `--entrypoint bash`** to run pytest directly: that skips
`run_tests.sh`, so no servers start and every `test_e2e_*` test fails with
connection-refused — which looks like a large regression but is only a
misconfigured run. If you genuinely want backend-only tests, keep the entrypoint
and set `PYTEST_TARGET`, or add `--ignore-glob='tests/test_e2e_*.py'`.

A full run takes ~11 minutes. Do not pipe it through `tail` — the summary line
is what you need and it is easy to truncate away. Redirect to a file instead.

### Lint, format, dev servers

These run on the host from `backend/` with the venv active:

```bash
# Backend
cd backend
. .venv/bin/activate
ruff check .            # lint
ruff format .           # format
uvicorn app.main:app --reload  # dev server

# Frontend
cd frontend
npm run dev             # dev server
npm run build           # production build
```

## Agent skills

### Issue tracker

GitHub Issues on `booji/KendoDojoManagement`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, label strings unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. The glossary is `UBIQUITOUS_LANGUAGE.md` (not `CONTEXT.md`); ADRs in `docs/adr/`. See `docs/agents/domain.md`.
