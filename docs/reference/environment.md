# Environment variables

The two env templates are the reference: every variable is documented in place,
next to the value it ships with. They are included here as they are in the
release you are reading.

## Quick self-host — `.env`

`./setup.sh` writes `.env` from this template, filling in the domain and
generating the secrets. It then writes `DATABASE_URL`,
`MIGRATION_DATABASE_URL`, `JWT_SECRET` and `SETUP_TOKEN` to files in
`secrets/`, which `docker-compose.yml` mounts under `/run/secrets` instead of
passing them as environment variables. After changing one of them in `.env`,
re-run `./setup.sh` so the files match.

The app reads each of those four from the file `<NAME>_FILE` names when that is
set, and from `<NAME>` otherwise. The dev and test stacks use `<NAME>`.

```bash
--8<-- ".env.example"
```

## Hardened deployment — `~/kendo/kendo-app.env`

Non-sensitive settings only. `DATABASE_URL`, `MIGRATION_DATABASE_URL`,
`JWT_SECRET` and `SETUP_TOKEN` are
podman secrets under the hardened deployment, not variables in this file — see
[Hardened deployment](../deployment.md).

```bash
--8<-- "deploy/env/kendo-app.env.example"
```
