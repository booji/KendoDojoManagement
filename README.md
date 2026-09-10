# KendoDojoManagement

Self-hosted web application for managing the members, sessions, and attendance of a kendo dojo. Single-dojo per instance, deployed with rootless Podman.

## Features

- **Members** — full profile management with grade history, coach/first-aider flags, and under-18 safeguarding fields
- **Sessions** — recurring templates and ad-hoc sessions with per-type colour coding, iCal feed, and a calendar/list toggle view
- **Attendance** — self check-in, one shareable check-in link per session, admin overrides, and visitor records
- **Grades** — enforced kendo grade progression (Mukyū → 8-dan) with full audit trail
- **Federations** — per-member federation memberships with membership numbers and renewal tracking. The catalogue starts empty; add the federations your dojo uses in Admin Settings. The [FIK affiliate list](https://www.kendo-fik.org/organization/affiliate) is the authoritative source for official names, abbreviations and websites.
- **Reports** — attendance and member-grade reports with CSV export
- **Auth** — passkey (WebAuthn) primary, email/password fallback, recovery codes, admin-issued recovery tokens, and break-glass CLI token
- **Security** — rate limiting, account lockout, security headers, CORS, and structured security event logging

## Container runtime

**Podman is the supported runtime.** It is what the project is developed and
tested against, and what the production deployment (`deploy/quadlet`) targets:
rootless, daemonless, systemd-native.

**Docker is best-effort and unverified.** The Compose files use no
Podman-specific syntax and the Makefile auto-detects `docker compose`, so it is
expected to work — but nothing here is tested under Docker and no parity is
promised. Bug reports are welcome; behaviour differences are not treated as
release blockers.

Every command in this README is written in its `podman` / `podman-compose`
form. With the `podman-docker` shim installed, `docker` and `docker compose`
are aliases for these, so both spellings work; a clean Podman install has no
`docker` binary at all, which is why the Podman form is the one written out.

Compose files keep their `docker-compose.*.yml` names — that is the filename
Compose implementations look for by convention, and `-f` names them explicitly
at every call site regardless of runtime.

## Deployment paths

Two supported ways to run this in production — pick one:

| Path | Files | Use when |
|------|-------|----------|
| **Compose** | `docker-compose.yml` + `.env` | You want a single host up quickly. Traefik terminates TLS on 80/443 with a Let's Encrypt certificate over the HTTP challenge. See [Quick start](#quick-start-production) below. |
| **Quadlet** | `deploy/quadlet` | You want the hardened deployment: rootless systemd units, Traefik with automatic TLS, network segmentation, Podman secrets, automated backups. See **[docs/deployment.md](docs/deployment.md)**. |

## Quick start (production)

> **Deploying to a real UAT/PROD host with HTTPS?** Use the Quadlet path
> instead — full runbook in **[docs/deployment.md](docs/deployment.md)**.
> The steps below are a minimal single-host HTTP trial only.

**1. Copy and fill in the environment file:**

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and JWT_SECRET at minimum
```

Passkeys are bound to the origin the browser uses, so also set `WEBAUTHN_RP_ID`
(bare host), `WEBAUTHN_ORIGIN` (full origin) and `CORS_ORIGINS` to your domain:

```
WEBAUTHN_RP_ID=dojo.example.com
WEBAUTHN_ORIGIN=https://dojo.example.com
CORS_ORIGINS=https://dojo.example.com
```

Generate a JWT secret:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**2. Point Traefik at the same domain:**

```bash
cd deploy/traefik/selfhost
cp traefik.yml.example traefik.yml                 # then edit the ACME email
cp dynamic/kendo.yml.example dynamic/kendo.yml     # then edit Host(`dojo.example.com`)
```

Both copies are gitignored, so upgrading with `git pull` cannot revert your
domain or your email to the shipped placeholders.

Certificates are issued over the HTTP challenge, so the host needs inbound port
80 and public DNS — no DNS-provider account. If you cannot have that, or you
already hold a certificate, use
`deploy/traefik/selfhost/dynamic/byo-cert.yml.example`.

Rootless Podman needs `net.ipv4.ip_unprivileged_port_start=80` to bind 80/443 —
see `deploy/sysctl-99-kendo-rootless-ports.conf`.

**3. Start the stack:**

```bash
make build   # build the production image
podman-compose up -d
```

Traefik serves the app on 443 and redirects 80 to it. The `app` service
publishes no host port of its own: every request arrives through the proxy,
which is what makes `TRUST_PROXY_XFF` (on by default here) safe — Traefik
overwrites `X-Forwarded-For` with the address it observed, so rate limiting and
account lockout see a client IP the client cannot choose. If you re-publish the
app's port, set `TRUST_PROXY_XFF=false` in the same edit.

Alembic migrations run automatically on startup via the entrypoint.
Uploaded logos and backgrounds persist in the `static_uploads` named volume, and
the database in `postgres_data` — both survive `down`/`up` and image rebuilds.

> **Upgrading a Compose stack first started before #385:** the image now runs as
> the unprivileged user `kendo` (uid 1001), but Podman only takes a volume's
> ownership from the image when the volume is *empty*, so a `static_uploads`
> created by the old root-running image stays root-owned and the first upload
> after the upgrade fails with a permission error. Chown it once:
>
> ```bash
> # Compose prefixes the volume with the project name — find it first:
> vol=$(podman volume ls --format '{{.Name}}' | grep static_uploads)
> podman unshare chown -R 1001:1001 \
>   "$(podman volume inspect "$vol" --format '{{.Mountpoint}}')"
> ```
>
> The Quadlet path needs no such step — `kendo-app.container` mounts the volume
> with `:U`, which chowns it on every start. Fresh stacks need nothing either.

## Development

### Prerequisites

- Podman + podman-compose (Docker Compose may work — see [Container runtime](#container-runtime))
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
- `proxy` — Traefik, on host ports **8443** (HTTPS) and **8080** (redirect to 8443)
- `backend` — FastAPI with hot-reload on file changes, on host port 8000
- `frontend` — Vite dev server with HMR, on host port 5173
- `db` — PostgreSQL 16, published on host port **5433**

**Open <https://dojo.localhost:8443>.** Browsers resolve `*.localhost` to
loopback, so no `/etc/hosts` entry is needed, and treat it as a secure context.
Traefik routes `/api`, `/health` and `/static` to the backend and everything
else to Vite, so the browser sits on one origin for both the UI and the API —
the same shape production has (see
`docs/adr/0001-single-origin-api-under-api-prefix.md`).

The proxy is not decoration. `.env.dev` sets `COOKIE_SECURE=true`,
`TRUST_PROXY_XFF=true` and a real `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN`, so
`Secure` cookies, passkey ceremonies and the `X-Forwarded-For` path that rate
limiting and lockout depend on are exercised here rather than for the first
time in production — the reasoning is in
`docs/adr/0002-traefik-in-the-dev-stack.md`.

`http://localhost:5173` and `http://localhost:8000` stay published as an escape
hatch for when a certificate is missing or HMR misbehaves through the proxy. On
those, cookies are not sent (they are `Secure`) and `X-Forwarded-For` is
whatever the caller claims — so do not test login or rate limiting there.

Vite's websocket setting is server-wide, so exactly one of the two origins gets
working HMR — the proxy by default. To hand it to `:5173` instead, start the
stack with the proxy origin emptied:

```bash
DEV_PROXY_ORIGIN= make dev
```

Then `:5173` live-reloads and `https://dojo.localhost:8443` does not (the page
still works; changes need a refresh). Put `DEV_PROXY_ORIGIN=` in `.env.dev` to
make it stick across runs.

#### The dev TLS certificate

The certificate is on the critical path: `.env.dev` sets `COOKIE_SECURE=true`,
and browsers refuse WebAuthn on a page with a certificate error — so a
*degraded* certificate looks like a perfectly healthy stack right up until the
first login or passkey ceremony fails.

**1. Generate.** `make dev` runs `make certs` for you, or run it directly:

```bash
make certs         # issue if missing, untrusted, or no longer covering dojo.localhost
make certs-force   # reissue unconditionally (no manual `rm` needed)
```

It says which generator it used. With [mkcert](https://github.com/FiloSottile/mkcert)
on your PATH the pair is issued by your local CA; without it you get a
self-signed pair and a warning saying so. Install mkcert and re-run `make certs`
— it notices the self-signed certificate and reissues. The pair lives in
`deploy/certs/` and is gitignored: per-machine, never committed.

**2. Trust the CA — on the machine the *browser* runs on.** `mkcert -install`
installs the CA into the trust store of the OS it runs on. If the stack and the
browser are on different systems, a successful-looking install does nothing for
the browser:

| Stack runs on | Browser runs on | Install the CA where |
|---------------|-----------------|----------------------|
| Linux (native) | the same Linux | `mkcert -install` in that shell |
| WSL2 | Windows | export `$(mkcert -CAROOT)/rootCA.pem` from WSL and import it into the Windows store (`certutil -addstore -user Root rootCA.pem`), or install mkcert on Windows and run `mkcert -install` there |
| A VM or remote dev box | your laptop | copy `rootCA.pem` off the box and import it into the laptop's store |

**Firefox keeps its own store.** It does not read the OS trust store. Either
install `nss-tools` (`certutil`) *before* `mkcert -install` so mkcert can add
the CA to Firefox's NSS database, or on Windows set
`security.enterprise_roots.enabled` to `true` in `about:config`.

**3. Verify.** Open <https://dojo.localhost:8443> — no warning, and a padlock.
That is the whole check; a warning means the browser does not trust the CA, not
that the certificate is malformed.

**4. Restart the proxy after any reissue.** Traefik loads the certificate at
startup and its file provider watches the config files, not the certificate
bytes. A replaced pair is not picked up until the proxy restarts (`make down &&
make dev`), which otherwise looks exactly like the new certificate not working.

When it goes wrong:

| Symptom | Cause | Fix |
|---------|-------|-----|
| Passkey ceremony fails, everything else looks fine | self-signed certificate | install mkcert, `make certs` |
| `mkcert -install` succeeded but the browser still warns | CA is in the wrong OS's trust store | see the table above |
| Chrome is happy, Firefox is not | Firefox's separate NSS store | `nss-tools` + `mkcert -install`, or `security.enterprise_roots.enabled` |
| The old warning persists after reissuing | Traefik still serving the startup certificate | `make down && make dev` |

If you need to get in without a certificate at all, `http://localhost:5173` is
still published — but cookies and passkeys do not work there, and HMR only
reaches it if the stack was started with `DEV_PROXY_ORIGIN=` (above).

#### Network layout

Two networks, mirroring the Quadlet production deployment in `deploy/quadlet`
(`kendo-edge` + `kendo-backend`):

| Network | Members | Purpose |
|---------|---------|---------|
| `edge` | `proxy`, `frontend`, `backend` | Traefik fronts both; carries the published host ports |
| `backend` | `backend`, `db` | The only path to PostgreSQL |

`frontend` is **not** on the `backend` network. It runs arbitrary npm
dependencies with `node_modules` mounted — the least trusted container in the
stack — so it cannot reach the database at all.

Nothing uses `network_mode: host` any more. Host-networked containers join no
Compose network, so there was nothing to segment, and the database ended up
binding host port 5432 directly (see below). The browser runs on the host and
never joins a Compose network, so browser reachability depends only on
published ports: `8443`/`8080` for the proxy, and the 1:1 `5173:5173` and
`8000:8000` escape hatches behind it.

Two runtime quirks are worth knowing, both verified on podman 5.6.0:

- **`isolate=true` is what actually enforces the split.** Podman's bridge
  networks are otherwise mutually routable *by IP* — the frontend cannot resolve
  `db`, but it can open a socket to the database's `10.89.x.x` address. The
  `driver_opts` in both Compose files close that. Docker isolates user-defined
  bridges natively, so the option is redundant there — and untested, like
  everything else on Docker. If a Docker version rejects the `driver_opts`
  key, dropping it loses nothing on that runtime.
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
then exited 1 while `podman-compose up -d db` still reported success. A
published port fails loudly on a collision, and 5433 avoids the common one
entirely.

To run two checkouts of this repo side by side, set a different `POSTGRES_PORT`
in `.env.dev` and change the port in `DATABASE_URL` in the same file to match.
The other four host ports are fixed and will collide: 8443 and 8080 (proxy),
5173 (Vite) and 8000 (uvicorn). Only one checkout's dev stack can be up at a
time unless you edit them — and 8443 also appears in `WEBAUTHN_ORIGIN`,
`CORS_ORIGINS`, the dev routing file and `server.hmr.clientPort`.
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
| `make` | List the targets (starts nothing) |
| `make dev` | Start the hot-reload dev stack |
| `make test` | Start the test watcher (re-runs pytest on every save) |
| `make build` | Build the production image |
| `make down` | Stop the stacks this checkout starts — dev and test |
| `make down-selfhost` | Stop the quick self-host stack — **takes the dojo offline** |
| `make certs` | Issue the `dojo.localhost` dev TLS certificate if it is missing or untrusted (run for you by `make dev`) |
| `make certs-force` | Reissue the dev TLS certificate unconditionally |
| `make logs` | Tail dev service logs |
| `make migrate` | Run `alembic upgrade head` in the running dev container |
| `make help` | List all targets |

The Makefile auto-detects `podman-compose` vs `docker compose`, so the targets run under either. That detection is kept because it costs nothing, not because Docker is tested — see [Container runtime](#container-runtime).

`make down` deliberately leaves the quick self-host alone: on a machine that is
actually serving a dojo, stopping it must be a deliberate act, so it has its own
target. The same reasoning already governs `make clean` refusing to remove the
production database volume.

`make dev` generates a per-machine `dojo.localhost` certificate under
`deploy/certs/` (gitignored) if one is missing, self-signed while mkcert is
available, or no longer covering the dev host. The full step — generate, trust,
verify, reissue, and the failure modes — is [The dev TLS
certificate](#the-dev-tls-certificate).

### Running tests

```bash
make test
```

This mounts `./backend` into a container alongside an ephemeral PostgreSQL instance and re-runs the full suite on every file change. The database is destroyed on `make down`.

One-shot run inside the running container:
```bash
podman-compose -f docker-compose.test.yml exec test pytest -q
```

A one-shot run of the whole suite, with optional pytest flags:
```bash
podman-compose -f docker-compose.test.yml run --rm test
podman-compose -f docker-compose.test.yml run --rm -e PYTEST_ARGS=-x test
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_members.py test
```

Pass pytest flags through `PYTEST_ARGS`, not positionally after the service
name: `podman-compose` treats trailing arguments as the container command, so
`run --rm test -x` fails with ``crun: executable file `-x` not found in
$PATH``. Only real `docker compose` forwards them. Both variables interpolate
unquoted, so keep values free of `*`, `?` and `[]`.

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
podman exec kendodojomanagement_db_1 pg_dump -U kendo_dev -d kendo_dev > dev.sql
podman rm -f kendodojomanagement_db_1
podman-compose -f docker-compose.dev.yml --env-file .env.dev up -d db
podman exec -i kendodojo-dev_db_1 psql -U kendo_dev -d kendo_dev < dev.sql
podman volume rm kendodojomanagement_postgres_dev_data   # once you are happy
```

Nothing needs carrying across for the test stack — its database is deliberately
volume-less and is rebuilt on every run.

## Break-glass recovery

Use this when the only admin is locked out and has no recovery codes.

```bash
podman exec kendo-app python -m app.cli create-recovery-token <email>
```

This prints a single-use plaintext token valid for **60 minutes**. Redeem it at:

- **API:** `POST /auth/recovery/redeem` — body `{"email": "<email>", "code": "<token>"}`
- **Login page:** enter the email and paste the token into the recovery code field

Security notes:
- Run this command on the server only — never over an untrusted network.
- The token is stored as a bcrypt hash; the plaintext is never persisted.
- Delete the token from your terminal history after use.
