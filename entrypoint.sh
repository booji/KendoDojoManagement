#!/usr/bin/env sh
set -e

# `init` hands over the deployment bundle baked into the image at /bundle —
# compose file, .example config, Quadlet units, backup scripts — so an operator
# configures a deployment without cloning the repository (ADR-0004):
#
#   podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x
#
# Bundle and app ship as one artefact, so the config always matches the image
# it configures. Writes nothing, needs no mounts, and is unreachable once the
# app is running.
if [ "$1" = "init" ]; then
  exec tar -C /bundle -c .
fi

# Migrations are NOT run here. They are their own unit — `migrate` in
# docker-compose.yml, kendo-migrate.service under Quadlet — which the app is
# ordered after (#391). Two owners of `alembic upgrade head` would race, and a
# migration that fails inside this container looks like an app crash.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
