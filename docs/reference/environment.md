# Environment variables

The two env templates are the reference: every variable is documented in place,
next to the value it ships with. They are included here as they are in the
release you are reading.

Both deployments take their app settings from the same template,
`deploy/env/kendo-app.env.example`. They differ only in where the secrets come
from.

## App settings — `kendo-app.env`

Non-sensitive settings only. The quick self-host keeps the file next to
`docker-compose.yml`, and the hardened deployment at `~/kendo/kendo-app.env`.
`./setup.sh` writes it from this template on both paths, filling in the domain.
The container reads the whole file, so every key in it reaches the app.

`DATABASE_URL`, `MIGRATION_DATABASE_URL`, `JWT_SECRET` and `SETUP_TOKEN` are
not in this file: see below for the quick self-host, and
[Hardened deployment](../deployment.md) for the podman secrets.

```bash
--8<-- "deploy/env/kendo-app.env.example"
```

## Quick self-host — `.env`

What `docker-compose.yml` itself interpolates (the image pin, the db's
settings) and the secrets. No container reads it whole, so the superuser login
in it never reaches the app (ADR-0007). `./setup.sh` writes `.env` from this
template, generating the secrets. It then writes `DATABASE_URL`,
`MIGRATION_DATABASE_URL`, `JWT_SECRET` and `SETUP_TOKEN` to files in
`secrets/`, which `docker-compose.yml` mounts under `/run/secrets` instead of
passing them as environment variables. After changing one of them in `.env`,
re-run `./setup.sh` so the files match.

The app reads each of those four from the file `<NAME>_FILE` names when that is
set, and from `<NAME>` otherwise. The dev and test stacks use `<NAME>`.

```bash
--8<-- ".env.example"
```
