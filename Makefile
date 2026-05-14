# Auto-detect container runtime: prefer podman-compose, fall back to docker compose
ifeq ($(shell command -v podman-compose 2>/dev/null),)
  COMPOSE  := docker compose
  RUNTIME  := docker
else
  COMPOSE  := podman-compose
  RUNTIME  := podman
endif

COMPOSE_DEV  := $(COMPOSE) -f docker-compose.dev.yml
COMPOSE_TEST := $(COMPOSE) -f docker-compose.test.yml
COMPOSE_PROD := $(COMPOSE) -f docker-compose.yml

.PHONY: dev test build down logs migrate help

## dev: Start the dev stack with hot-reload
dev:
	$(COMPOSE_DEV) down --remove-orphans 2>/dev/null || true
	$(RUNTIME) rm -f kendodojomanagement_db_1 kendodojomanagement_backend_1 kendodojomanagement_frontend_1 2>/dev/null || true
	$(COMPOSE_DEV) up

## test: Start the test watcher stack
test:
	$(COMPOSE_TEST) up

## build: Build the production image
build:
	$(COMPOSE_PROD) build

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
