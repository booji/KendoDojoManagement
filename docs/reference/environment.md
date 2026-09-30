# Environment variables

The two env templates are the reference: every variable is documented in place,
next to the value it ships with. They are included here as they are in the
release you are reading.

## Quick self-host — `.env`

`./setup.sh` writes `.env` from this template, filling in the domain and
generating the three secrets.

```bash
--8<-- ".env.example"
```

## Hardened deployment — `~/kendo/kendo-app.env`

Non-sensitive settings only. `DATABASE_URL`, `JWT_SECRET` and `SETUP_TOKEN` are
podman secrets under the hardened deployment, not variables in this file — see
[Hardened deployment](../deployment.md).

```bash
--8<-- "deploy/env/kendo-app.env.example"
```
