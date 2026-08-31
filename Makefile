# Auto-detect container runtime: prefer podman-compose, fall back to docker compose
ifeq ($(shell command -v podman-compose 2>/dev/null),)
  COMPOSE  := docker compose
  RUNTIME  := docker
else
  COMPOSE  := podman-compose
  RUNTIME  := podman
endif

# --env-file makes .env.dev available for variable substitution in the compose
# file itself (POSTGRES_PORT), not just inside the containers (#275).
COMPOSE_DEV  := $(COMPOSE) -f docker-compose.dev.yml --env-file .env.dev
COMPOSE_TEST := $(COMPOSE) -f docker-compose.test.yml
COMPOSE_PROD := $(COMPOSE) -f docker-compose.yml

.PHONY: dev test build down logs migrate help

## dev: Start the dev stack with hot-reload
dev:
	$(COMPOSE_DEV) down --remove-orphans 2>/dev/null || true
	$(RUNTIME) rm -f kendodojomanagement_db_1 kendodojomanagement_backend_1 kendodojomanagement_frontend_1 2>/dev/null || true
	# --build for the same reason as the test target below (#221, #332): without
	# it Compose reuses the cached backend-dev-deps image, so a newly pinned
	# runtime dependency is simply absent and the backend dies at import with
	# ModuleNotFoundError. Layer caching keeps this a no-op otherwise.
	$(COMPOSE_DEV) up --build

## test: Start the test watcher stack (rebuilds the image so pinned dev deps are present)
test:
	# --build rebuilds when the Dockerfile or requirements*.txt change, so a
	# newly pinned dev dependency (e.g. freezegun) can't be missing from a stale
	# cached image and masquerade as a collection error (see #221). Docker layer
	# caching keeps this a no-op when nothing relevant changed.
	$(COMPOSE_TEST) up --build

## build: Build the production image (re-resolving base images)
build:
	# --pull re-resolves node:22-slim and python:3.13-slim against the registry.
	# Both tags float to the latest patch upstream, but a build reuses whatever
	# digest is already in local storage, so without this a machine keeps
	# building on the base it first pulled — silently, for as long as it lives.
	$(COMPOSE_PROD) build --pull

## down: Stop all running services (dev, test, and prod)
down:
	$(COMPOSE_DEV) down --remove-orphans
	$(COMPOSE_TEST) down --remove-orphans
	$(COMPOSE_PROD) down --remove-orphans

## logs: Tail logs from running dev services
logs:
	$(COMPOSE_DEV) logs -f

## migrate: Run alembic upgrade head inside the running dev backend container
migrate:
	$(COMPOSE_DEV) exec backend alembic upgrade head

## help: List all targets with descriptions
help:
	@grep -E '^## ' Makefile | sed 's/## //' | column -t -s ':'
