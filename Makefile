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

# Per-machine TLS material for the dev stack. Gitignored, never committed.
CERT_DIR := deploy/certs

# A bare `make` used to run the first target, which was `dev` — an exploratory
# keystroke started a foreground image build. It now lists the targets (#373).
.DEFAULT_GOAL := help

.PHONY: dev test build down down-selfhost clean logs migrate certs help

## certs: Generate the dev TLS certificate if one is missing
certs:
	# set -e, and no output swallowed: a generator that fails must say so and
	# stop, rather than leave `make dev` believing it has TLS material. Both
	# halves of the pair are checked — a cert with a missing key is not a skip.
	@set -e; \
	  if [ -f $(CERT_DIR)/dojo.localhost.pem ] && [ -f $(CERT_DIR)/dojo.localhost-key.pem ]; then \
	    exit 0; \
	  fi; \
	  mkdir -p $(CERT_DIR); \
	  if command -v mkcert >/dev/null 2>&1; then \
	    mkcert -cert-file $(CERT_DIR)/dojo.localhost.pem \
	           -key-file $(CERT_DIR)/dojo.localhost-key.pem \
	           dojo.localhost localhost 127.0.0.1 ::1; \
	  elif command -v openssl >/dev/null 2>&1; then \
	    openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
	      -subj '/CN=dojo.localhost' \
	      -addext 'subjectAltName=DNS:dojo.localhost,DNS:localhost,IP:127.0.0.1' \
	      -keyout $(CERT_DIR)/dojo.localhost-key.pem \
	      -out $(CERT_DIR)/dojo.localhost.pem; \
	    echo 'mkcert not on PATH - generated a self-signed certificate. Passkey ceremonies may misbehave until you install a local CA (mkcert -install).'; \
	  else \
	    echo 'neither mkcert nor openssl on PATH - cannot generate the dev certificate.'; \
	    echo 'The dev stack serves https://dojo.localhost:8443 and .env.dev sets COOKIE_SECURE=true,'; \
	    echo 'so without TLS there is no origin that can hold a session. Install mkcert or openssl.'; \
	    exit 1; \
	  fi; \
	  chmod 600 $(CERT_DIR)/dojo.localhost-key.pem

## dev: Start the dev stack with hot-reload
dev: certs
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

## down: Stop the stacks this checkout starts (dev and test)
down:
	# Deliberately not the quick self-host. On a laptop that leg only prints
	# variable-substitution warnings for an absent .env; on a self-hosting
	# machine it takes the dojo offline. Same reasoning as `clean` declining to
	# remove the production volume: stopping the dojo is a deliberate act.
	$(COMPOSE_DEV) down --remove-orphans
	$(COMPOSE_TEST) down --remove-orphans

## down-selfhost: Stop the quick self-host stack - takes the dojo offline
down-selfhost:
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
