# KendoDojoManagement

Self-hosted web application for managing the members, sessions, and attendance of a kendo dojo. Single-dojo per instance, deployable with Docker Compose (or Podman).

## Features

- **Members** — full profile management with grade history, coach/first-aider flags, and under-18 safeguarding fields
- **Sessions** — recurring templates and ad-hoc sessions with per-type colour coding, iCal feed, and a calendar/list toggle view
- **Attendance** — self check-in, shareable check-in tokens (hashed at rest), admin overrides, and visitor records
- **Grades** — enforced kendo grade progression (Mukyū → 8-dan) with full audit trail
- **Federations** — per-member federation memberships with membership numbers and renewal tracking. The catalogue starts empty; add the federations your dojo uses in Admin Settings. The [FIK affiliate list](https://www.kendo-fik.org/organization/affiliate) is the authoritative source for official names, abbreviations and websites.
- **Reports** — attendance and member-grade reports with CSV export
- **Auth** — passkey (WebAuthn) primary, email/password fallback, recovery codes, admin-issued recovery tokens, and break-glass CLI token
- **Security** — rate limiting, account lockout, security headers, CORS, and structured security event logging

## Quick start (production)

> **Deploying to a real UAT/PROD host with HTTPS?** Follow the full runbook in
> **[docs/deployment.md](docs/deployment.md)** — rootless Podman + Quadlet, Traefik
> for automatic TLS, network segmentation, Podman secrets, and automated backups.
> The steps below are a minimal single-host HTTP trial only.

**1. Copy and fill in the environment file:**

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and JWT_SECRET at minimum
```

Passkeys are bound to the origin the browser uses, so also set `WEBAUTHN_RP_ID`
(bare host), `WEBAUTHN_ORIGIN` (full origin) and `CORS_ORIGINS` to match how you
reach the app. For a localhost trial the defaults below work:

```
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGIN=http://localhost:8000
CORS_ORIGINS=http://localhost:8000
COOKIE_SECURE=false   # localhost is not HTTPS, so Secure cookies won't be sent
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
Uploaded logos and backgrounds persist in the `static_uploads` named volume, and
the database in `postgres_data` — both survive `down`/`up` and image rebuilds.

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
- `backend` — FastAPI with hot-reload on file changes, on host port 8000
- `frontend` — Vite dev server with HMR, on host port 5173
- `db` — PostgreSQL 16, published on host port **5433**

The frontend proxies `/api` to the backend, so everything is available at `http://localhost:5173`.

#### Network layout

Two networks, mirroring the Quadlet production deployment in `deploy/quadlet`
(`kendo-edge` + `kendo-backend`):

| Network | Members | Purpose |
|---------|---------|---------|
| `edge` | `frontend`, `backend` | Vite proxies `/api` to the backend; carries the published host ports |
| `backend` | `backend`, `db` | The only path to PostgreSQL |

`frontend` is **not** on the `backend` network. It runs arbitrary npm
dependencies with `node_modules` mounted — the least trusted container in the
stack — so it cannot reach the database at all.

Nothing uses `network_mode: host` any more. Host-networked containers join no
Compose network, so there was nothing to segment, and the database ended up
binding host port 5432 directly (see below). Host ports are published 1:1
(`5173:5173`, `8000:8000`), so every `localhost` URL is unchanged: the browser
runs on the host and never joins a Compose network, so browser reachability
depends only on published ports.

Two runtime quirks are worth knowing, both verified on podman 5.6.0:

- **`isolate=true` is what actually enforces the split.** Podman's bridge
  networks are otherwise mutually routable *by IP* — the frontend cannot resolve
  `db`, but it can open a socket to the database's `10.89.x.x` address. The
  `driver_opts` in both Compose files close that. Docker isolates user-defined
  bridges natively and does not need the option.
- **The `backend` network is not `internal: true`**, unlike `Internal=true` on
  `kendo-backend.network` in `deploy/quadlet`. Podman disables DNS on internal
  networks (`dnsname and internal networks are incompatible`), so the service
  name `db` stops resolving and the backend cannot connect. The trade is the
  database's outbound route, which cannot be removed on Podman without also
  losing service-name DNS.

#### Why the database is on 5433, not 5432

`db` publishes a mapped port rather than binding the host's. Host networking
used to make it bind host port 5432 directly — the conventional PostgreSQL port.
Anything else on the machine holding that port (a system install, another
project's stack, a leftover container) claimed it first, and the dev database
then exited 1 while `docker compose up -d db` still reported success. A
published port fails loudly on a collision, and 5433 avoids the common one
entirely.

To run two checkouts of this repo side by side, set a different `POSTGRES_PORT`
in `.env.dev` and change the port in `DATABASE_URL` in the same file to match.
The frontend port must stay mapped 1:1 (`5173:5173`): Vite's HMR client infers
the websocket port from the browser's location, so publishing it on a different
host port needs `server.hmr.clientPort` set in `frontend/vite.config.ts`.

#### Connecting from the host

The port is published on `127.0.0.1` only — the dev credentials are weak and
committed to the repo, so the database is deliberately not reachable from the
LAN. Host-side tooling (`alembic`, `psql`, a one-off script) must point at the
published port, *not* 5432, and address `127.0.0.1` rather than `localhost`
(which can resolve to `::1`, where nothing is listening):

```bash
export DATABASE_URL=postgresql+asyncpg://kendo_dev:kendo_dev_password@127.0.0.1:5433/kendo_dev
psql -h 127.0.0.1 -p 5433 -U kendo_dev -d kendo_dev
```

If you get `password authentication failed for user "kendo_dev"` on port 5432,
you are talking to a *different* PostgreSQL — the credentials are not the
problem, the port is.

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
| `docker-compose.yml` | Production stack (app + PostgreSQL, named volumes for db data and uploads) |
| `docker-compose.dev.yml` | Dev stack with bind-mounted source and hot-reload |
| `docker-compose.test.yml` | Test watcher stack with ephemeral PostgreSQL |
| `.env.example` | Template for production secrets |
| `.env.dev` | Dev defaults (safe to commit) |
| `.env.test` | Test defaults (safe to commit) |

Each stack sets an explicit Compose project name — `kendodojo`, `kendodojo-dev`
and `kendodojo-test`. Without it Compose derives the name from the directory, so
all three resolved to the same containers, networks and volumes: starting the
dev database silently replaced the test one, and `down` on either file removed
containers belonging to the other.

If you have a checkout from before this change, your old containers and volumes
are still named after the directory (`kendodojomanagement_*`) and are now
orphaned. To carry dev data across:

```bash
docker exec kendodojomanagement_db_1 pg_dump -U kendo_dev -d kendo_dev > dev.sql
docker rm -f kendodojomanagement_db_1
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d db
docker exec -i kendodojo-dev_db_1 psql -U kendo_dev -d kendo_dev < dev.sql
docker volume rm kendodojomanagement_postgres_dev_data   # once you are happy
```

Nothing needs carrying across for the test stack — its database is deliberately
volume-less and is rebuilt on every run.

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
