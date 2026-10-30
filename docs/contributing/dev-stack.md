# Dev stack

## Prerequisites

- Podman + podman-compose (Docker Compose may work — see [Container runtime](../index.md#container-runtime))
- Python 3.13 + a virtual environment (`python3 -m venv backend/.venv`)
- Node 22

## Get the code

Operators do not need a clone — the release image carries its own deployment
bundle ([Quick self-host](../install/quick-self-host.md)). Contributors do:

```bash
git clone https://github.com/booji/KendoDojoManagement.git
cd KendoDojoManagement
```

## Environment

Copy the dev env file (safe to commit — contains no real secrets):
```bash
cp .env.dev .env.dev.local   # optional local overrides
```

No edits needed to get started, but the backend container does not load
`.env.dev` (only `db` does): its settings are interpolated from it, which needs
`--env-file .env.dev` on every Compose command. `make dev` passes it; a bare
`podman-compose -f docker-compose.dev.yml up` starts the backend with
`JWT_SECRET`, `SETUP_TOKEN` and the rest blank (#483).

## Start the dev stack

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

### The dev TLS certificate

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

### Network layout

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

### Why the database is on 5433, not 5432

`db` publishes a mapped port rather than binding the host's. Host networking
used to make it bind host port 5432 directly — the conventional PostgreSQL port.
Anything else on the machine holding that port (a system install, another
project's stack, a leftover container) claimed it first, and the dev database
then exited 1 while `podman-compose up -d db` still reported success. A
published port fails loudly on a collision, and 5433 avoids the common one
entirely.

To run two checkouts of this repo side by side, set a different `POSTGRES_PORT`
in `.env.dev` and change the port in both database URLs in the same file to match.
The other four host ports are fixed and will collide: 8443 and 8080 (proxy),
5173 (Vite) and 8000 (uvicorn). Only one checkout's dev stack can be up at a
time unless you edit them — and 8443 also appears in `WEBAUTHN_ORIGIN`,
`CORS_ORIGINS`, the dev routing file and `server.hmr.clientPort`.
The frontend port must stay mapped 1:1 (`5173:5173`): Vite's HMR client infers
the websocket port from the browser's location, so publishing it on a different
host port needs `server.hmr.clientPort` set in `frontend/vite.config.ts`.

### Connecting from the host

The port is published on `127.0.0.1` only — the dev credentials are weak and
committed to the repo, so the database is deliberately not reachable from the
LAN. Host-side tooling (`alembic`, `psql`, a one-off script) must point at the
published port, *not* 5432, and address `127.0.0.1` rather than `localhost`
(which can resolve to `::1`, where nothing is listening):

```bash
export DATABASE_URL=postgresql+asyncpg://kendo_dev:kendo_dev_password@127.0.0.1:5433/kendo_dev
psql -h 127.0.0.1 -p 5433 -U kendo_dev -d kendo_dev
```

That is the superuser, `MIGRATION_DATABASE_URL` in `.env.dev`, which alembic
needs. The backend itself connects as the restricted `kendo_app` user that the
`migrate` service creates, and refuses to start as a superuser
([ADR-0007](../adr/0007-the-app-connects-as-a-least-privilege-database-user.md)).
After adding a migration, `make migrate` runs that service again.

If you get `password authentication failed for user "kendo_dev"` on port 5432,
you are talking to a *different* PostgreSQL — the credentials are not the
problem, the port is.
