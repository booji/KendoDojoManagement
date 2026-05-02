# KendoDojoManagement

Self-hosted web application for managing the members, sessions, and attendance of a kendo dojo. Single-dojo per instance, deployable with Docker Compose (or Podman).

## Features

- **Members** — full profile management with grade history, coach/first-aider flags, and under-18 safeguarding fields
- **Sessions** — recurring templates and ad-hoc sessions with per-type colour coding, iCal feed, and a calendar/list toggle view
- **Attendance** — self check-in, shareable check-in tokens (hashed at rest), admin overrides, and visitor records
- **Grades** — enforced kendo grade progression (Mukyū → 8-dan) with full audit trail
- **Reports** — attendance and member-grade reports with CSV export
- **Auth** — passkey (WebAuthn) primary, email/password fallback, recovery codes, admin-issued recovery tokens, and break-glass CLI token
- **Security** — rate limiting, account lockout, security headers, CORS, and structured security event logging

## Quick start (production)

**1. Copy and fill in the environment file:**

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and JWT_SECRET at minimum
```

Generate a JWT secret:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**2. Start the stack:**

```bash
make build   # build the production image
docker compose up -d
```

Or with Podman:
```bash
podman-compose up -d
```

The app runs on port 8000. Alembic migrations run automatically on startup via the entrypoint.

## Development

### Prerequisites

- Docker Compose **or** Podman + podman-compose
- Python 3.13 + a virtual environment (`python3 -m venv backend/.venv`)
- Node 22

### Environment

Copy the dev env file (safe to commit — contains no real secrets):
```bash
cp .env.dev .env.dev.local   # optional local overrides
```

`.env.dev` is already wired into `docker-compose.dev.yml`. No edits needed to get started.

### Start the dev stack

```bash
make dev
```

This starts:
- `backend` — FastAPI with hot-reload on file changes
- `frontend` — Vite dev server with HMR
- `db` — PostgreSQL 16

The frontend proxies `/api` to the backend, so everything is available at `http://localhost:5173`.

### Useful `make` targets

| Target | What it does |
|--------|-------------|
| `make dev` | Start the hot-reload dev stack |
| `make test` | Start the test watcher (re-runs pytest on every save) |
| `make build` | Build the production image |
| `make down` | Stop all running services |
| `make logs` | Tail dev service logs |
| `make migrate` | Run `alembic upgrade head` in the running dev container |
| `make help` | List all targets |

The Makefile auto-detects `podman-compose` vs `docker compose` — no changes needed for either runtime.

### Running tests locally (without Docker)

```bash
cd backend
. .venv/bin/activate
pytest -q --ignore=tests/test_e2e_*.py
```

### Running tests in the container

```bash
make test
```

This mounts `./backend` into a container alongside an ephemeral PostgreSQL instance and re-runs the full suite on every file change. The database is destroyed on `make down`.

One-shot run inside the running container:
```bash
# docker:
docker compose -f docker-compose.test.yml exec test pytest -q
# podman:
podman-compose -f docker-compose.test.yml exec test pytest -q
```

## Container architecture

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `backend-deps` → `backend-dev-deps` → `frontend-deps` → `frontend-build` → `prod` |
| `docker-compose.yml` | Production stack (app + PostgreSQL with named volume) |
| `docker-compose.dev.yml` | Dev stack with bind-mounted source and hot-reload |
| `docker-compose.test.yml` | Test watcher stack with ephemeral PostgreSQL |
| `.env.example` | Template for production secrets |
| `.env.dev` | Dev defaults (safe to commit) |
| `.env.test` | Test defaults (safe to commit) |

## Break-glass recovery

Use this when the only admin is locked out and has no recovery codes.

```bash
docker exec kendo-app python -m app.cli create-recovery-token <email>
# podman:
podman exec kendo-app python -m app.cli create-recovery-token <email>
```

This prints a single-use plaintext token valid for **60 minutes**. Redeem it at:

- **API:** `POST /auth/recovery/redeem` — body `{"email": "<email>", "code": "<token>"}`
- **Login page:** enter the email and paste the token into the recovery code field

Security notes:
- Run this command on the server only — never over an untrusted network.
- The token is stored as a bcrypt hash; the plaintext is never persisted.
- Delete the token from your terminal history after use.
