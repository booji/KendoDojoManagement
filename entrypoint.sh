#!/usr/bin/env sh
set -e

# Migrations are NOT run here. They are their own unit — `migrate` in
# docker-compose.yml, kendo-migrate.service under Quadlet — which the app is
# ordered after (#391). Two owners of `alembic upgrade head` would race, and a
# migration that fails inside this container looks like an app crash.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
