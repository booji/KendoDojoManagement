# Traefik runs in the development stack

The development Compose stack runs Traefik in front of the app, serving
`https://dojo.localhost:8443` with a locally-generated certificate, and
`.env.dev` sets `COOKIE_SECURE=true` and `TRUST_PROXY_XFF=true` to match the
hardened deployment.

## Context

A reverse proxy in a dev stack looks like gratuitous machinery. It is there for
three behaviours that are otherwise exercised for the first time in production:
passkey ceremonies bound to a real `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` over
TLS, `Secure` session cookies, and the `X-Forwarded-For` path that rate
limiting and account lockout depend on. Each of these fails silently or not at
all in a plain-HTTP `localhost:5173` stack, and each produces a
healthy-looking deployment that rejects logins or mis-attributes client IPs.

## Considered options

`dojo.localhost` needs no `/etc/hosts` entry (browsers resolve `*.localhost` to
loopback) and is a secure context, so it beats a `.test` domain. Ports 8443/8080
are used rather than 443/80 so that running the dev stack does not require the
`net.ipv4.ip_unprivileged_port_start` sysctl; the port appears in
`WEBAUTHN_ORIGIN` but not in `WEBAUTHN_RP_ID`, which stays the bare host.
Traefik is configured through the file provider, as in `deploy/quadlet` — the
socket-based label provider was rejected there deliberately and copying it into
development would diverge exactly where the point is to match.

## Consequences

The direct `:5173` and `:8000` ports stay published as an escape hatch when a
certificate is missing or HMR misbehaves through the proxy, so the proxy is
never the only way in. Vite needs `allowedHosts` and an explicit `wss` HMR
client port to serve through it. The test stack deliberately does not get
Traefik: the e2e suite drives Vite and uvicorn in one container, and an ~11
minute suite should not grow a proxy hop for fidelity it does not test.
