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

.PHONY: dev test build down clean logs migrate help

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

## build: Build the production image
build:
	$(COMPOSE_PROD) build

## down: Stop all running services (dev, test, and prod)
down:
	$(COMPOSE_DEV) down --remove-orphans
	$(COMPOSE_TEST) down --remove-orphans
	$(COMPOSE_PROD) down --remove-orphans

## clean: Remove this project's containers, dev/test volumes and images
clean:
	# Dev and test data is disposable — the stacks recreate it on next start.
	$(COMPOSE_DEV) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) down -v --remove-orphans 2>/dev/null || true
	# No -v for prod: that volume holds a real dojo's database. Removing it is
	# a deliberate act, not branch cleanup — `podman volume rm kendodojo_pgdata`.
	$(COMPOSE_PROD) down --remove-orphans 2>/dev/null || true
	# `run --rm` containers survive an interrupted run (Ctrl-C, a timeout) and
	# keep their image and anonymous volumes alive with them. `down` does not
	# know about them; they are not services.
	@ids=$$($(RUNTIME) ps -aq --filter name=kendodojo); \
	  [ -n "$$ids" ] && $(RUNTIME) rm -f $$ids || echo "no stray containers"
	@ids=$$($(RUNTIME) images -q --filter reference='kendodojo*'); \
	  [ -n "$$ids" ] && $(RUNTIME) rmi -f $$ids || echo "no project images"
	# The test db declares no named volume, but postgres:16-alpine has a VOLUME
	# directive — so every start strands an unlabelled ~48MB anonymous volume
	# that `down -v` does not collect. Those have 64-hex names; every volume
	# worth keeping (kendodojo_pgdata above all) is named, so the pattern is
	# the safety rail. `volume prune` would take the production database.
	@ids=$$($(RUNTIME) volume ls -q --filter dangling=true | grep -E '^[0-9a-f]{64}$$'); \
	  [ -n "$$ids" ] && $(RUNTIME) volume rm $$ids || echo "no anonymous volumes"
	# Every --build that changes a layer orphans the previous one. Dangling
	# images belong to no project, so this is the one system-wide step.
	$(RUNTIME) image prune -f
	$(RUNTIME) system df

## logs: Tail logs from running dev services
logs:
	$(COMPOSE_DEV) logs -f

## migrate: Run alembic upgrade head inside the running dev backend container
migrate:
	$(COMPOSE_DEV) exec backend alembic upgrade head

## help: List all targets with descriptions
help:
	@grep -E '^## ' Makefile | sed 's/## //' | column -t -s ':'
