# The app serves the SPA and the API from one origin, with the API under `/api`

The built SPA is copied into the app image and served by FastAPI itself, and
every API router is mounted under an `/api` prefix, so browser and API share a
single origin in development, the quick self-host and the hardened deployment
alike. `/health` (used by container healthchecks) and the `/static/*` upload
mounts stay at the root.

## Context

The frontend already called `/api/...`, but the routers were mounted at the
root and Vite's dev proxy rewrote the prefix away. That worked only in
development: in both production stacks `/` and `/api/*` returned 404, because
nothing served the SPA and no route answered the prefixed paths — despite
`docs/deployment.md` describing exactly this arrangement. Single-origin also
keeps cookie-based auth and WebAuthn simple: no CORS preflight on the app's own
calls, no cross-site cookie rules, one origin for `WEBAUTHN_ORIGIN` to match.

## Considered options

Letting the reverse proxy own the split instead — Traefik routing `/api` to the
backend with a StripPrefix middleware and `/` to a separate SPA container — was
rejected. It contradicts the hardened deployment's single `kendo-app`
container, adds a container and a middleware to production for no gain, and
leaves the app image unable to serve itself when run without a proxy.

## Consequences

The SPA catch-all mount is conditional on `static/index.html` existing, so the
development image (which runs from source, with Vite serving the frontend) does
not need a build step. Vite's `/api` rewrite is gone: development and
production now use identical URLs, which is what makes a proxy in front of the
dev stack meaningful at all — see ADR-0002.
