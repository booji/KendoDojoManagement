# KendoDojoManagement

Self-hosted web application for managing the members, sessions, and attendance of a kendo dojo. Single-dojo per instance, deployed with rootless Podman.

--8<-- "README.md:features"

## Container runtime

**Podman is the supported runtime.** It is what the project is developed and
tested against, and what the production deployment (`deploy/quadlet`) targets:
rootless, daemonless, systemd-native.

**Docker is best-effort and unverified.** The Compose files use no
Podman-specific syntax and the Makefile auto-detects `docker compose`, so it is
expected to work — but nothing here is tested under Docker and no parity is
promised. Bug reports are welcome; behaviour differences are not treated as
release blockers.

Every command in these docs is written in its `podman` / `podman-compose`
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
| **Compose** | `docker-compose.yml` + `.env` | You want a single host up quickly. Traefik terminates TLS on 80/443 with a Let's Encrypt certificate over the HTTP challenge. See [Quick self-host](install/quick-self-host.md). |
| **Quadlet** | `deploy/quadlet` | You want the hardened deployment: rootless systemd units, Traefik with automatic TLS, network segmentation, Podman secrets, automated backups. `./setup.sh --quadlet` lays it all down; full runbook in **[Hardened deployment](deployment.md)**. |
