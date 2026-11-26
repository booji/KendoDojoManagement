# Container architecture

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `backend-deps` → `backend-dev-deps` → `frontend-deps` → `frontend-build` → `prod` |
| `docker-compose.yml` | Production stack (app + PostgreSQL, named volumes for db data and uploads) |
| `docker-compose.dev.yml` | Dev stack with bind-mounted source and hot-reload |
| `docker-compose.test.yml` | Test watcher stack with ephemeral PostgreSQL |
| `.env.example` | Template for the production stack's `.env`: image pin, db settings and secrets |
| `deploy/env/kendo-app.env.example` | Template for the app settings (`kendo-app.env`), shared with the Quadlet deployment |
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
