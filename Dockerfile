FROM python:3.13-slim AS backend-deps
WORKDIR /app
# tzdata provides /usr/share/zoneinfo so the TZ env var actually changes the
# container's local time (Debian slim ships no timezone database otherwise).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
# Upgrade pip first so the image ships the CVE-fixed pip (issue #235). pip is
# build-only tooling, but this keeps the image's pip current too.
RUN pip install --no-cache-dir --upgrade pip
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM backend-deps AS backend-dev-deps
COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
# curl belongs to this stage rather than the e2e one below: run_tests.sh gates
# on `curl http://localhost:8000/health` before pytest (#316), and the
# backend-only CI job (#336) runs that script against this image.
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

FROM backend-dev-deps AS backend-e2e-deps
# Install Node.js 22 (for Vite dev server) and Playwright system deps
RUN apt-get update && apt-get install -y gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN playwright install --with-deps chromium

FROM node:22-slim AS frontend-deps
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS prod
WORKDIR /app

# tzdata so the TZ env var honours the configured timezone in production too.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=backend-deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin
COPY backend/ ./
COPY --from=frontend-build /frontend/dist ./static
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# The deployment bundle the image hands over with `init` (ADR-0004): everything
# an operator needs around the app, shipped on the same version axis as the app
# itself so config from the tip never drives a pinned image.
#
# The dev-only paths under deploy/ (certs, traefik/dev) are kept out by
# .dockerignore rather than deleted after the COPY: a layer keeps what a later
# `rm` removes, so a dev machine's TLS keys would still be extractable from the
# pushed image.
COPY setup.sh docker-compose.yml .env.example /bundle/
COPY deploy/ /bundle/deploy/

# The tag the bundle was extracted from, so setup.sh writes a real pin into
# .env instead of prompting or defaulting blind (ADR-0004). Unset on a
# contributor's `make build`: setup.sh then keeps .env.example's own default.
ARG KENDO_IMAGE_REF=""
RUN if [ -n "$KENDO_IMAGE_REF" ]; then printf '%s\n' "$KENDO_IMAGE_REF" > /bundle/.image-tag; fi

# Run unprivileged. Rootless Podman already maps container-root to an
# unprivileged host user, but inside the container root can rewrite the app's
# own code and site-packages, so a compromise survives a restart (#385).
#
# /app/uploads must exist and belong to `kendo` here: it is a volume mount
# point that nothing else creates (main.py mkdirs the leaf directories at
# import, i.e. after the mount), and Podman takes a fresh named volume's
# ownership from the image directory it shadows. A volume left over from a
# root-running image keeps its old ownership — deploy/quadlet handles that with
# `:U` on the mount; the Compose path needs the one-off chown in docs/deployment.md.
RUN useradd --system --uid 1001 --create-home --shell /usr/sbin/nologin kendo && \
    mkdir -p /app/uploads/logos /app/uploads/backgrounds && \
    chown -R kendo:kendo /app/uploads
USER kendo

ENV DATABASE_URL=""
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
