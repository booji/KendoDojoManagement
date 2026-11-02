# Quick self-host

This is a supported production path for a single dojo: one host, Traefik
terminating TLS with a Let's Encrypt certificate, three commands.

> **Outgrowing it?** The [Hardened deployment](../deployment.md) is what you
> graduate to — the same `setup.sh`, run as `./setup.sh --quadlet`, adds
> systemd units, Podman secrets, network segmentation and automated backups.

**1. Get the deployment files:**

The release image carries the files a deployment needs — this compose file, the
`.example` config, the Quadlet units, the backup scripts and `setup.sh` — so
there is no clone and no build (ADR-0004):

```bash
podman run --rm ghcr.io/booji/kendodojomanagement:0.1 init | tar -x
```

(Working from a checkout instead? Skip that — the files are already here.)

**2. Configure it:**

```bash
./setup.sh
```

It asks for your domain and an ACME email, generates `POSTGRES_PASSWORD`,
`JWT_SECRET`, `SETUP_TOKEN` and the app's own database password — the app
connects as `kendo_app`, which can only read and write rows, and the superuser
login goes to the `migrate` service alone — and writes `.env` plus
`deploy/traefik/selfhost/traefik.yml` and `dynamic/kendo.yml` from their
`.example` files. The app's secrets also go to files in `secrets/`, which the
containers get mounted as files rather than as environment variables; after
changing one in `.env`, re-run `./setup.sh` so they match. One domain answer reaches all three passkey-bound settings
(`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `CORS_ORIGINS`) and the Traefik `Host()`
rule — an `RP_ID` typo is the whole "passkeys silently don't work" failure
class, so it is worth not typing four times.

TLS is one question with four answers: Let's Encrypt production, Let's Encrypt
staging (rehearse a new domain without burning the production rate limit),
bring your own certificate, or skip. Orthogonally, the ACME challenge is
HTTP-01 (default, needs inbound 80), TLS-ALPN-01 (needs inbound 443 only — the
answer when an ISP blocks 80) or DNS-01 (no inbound ports; it prompts for your
lego provider slug and prints the credentials that provider wants).

Re-running is safe: existing secrets are carried forward rather than
regenerated, and any file it rewrites is kept as `.bak`. The written files are
gitignored, so upgrading cannot revert your domain or email to the shipped
placeholders. Prefer doing it by hand? Every file it writes has a documented
`.example` next to it.

The script also checks the five host prerequisites — Podman, the
`net.ipv4.ip_unprivileged_port_start=80` sysctl rootless Podman needs to bind
80/443, the firewall, the `kendo` user and `loginctl enable-linger` — and
prints the exact `sudo` command for each one that is missing. It never
escalates itself; you run those.

**3. Check, then start the stack:**

```bash
./setup.sh check       # green? then:
podman-compose up -d   # pulls ghcr.io/booji/kendodojomanagement:0.1
```

`check` looks at what the app cannot see from inside its container, the things
that otherwise surface as a browser error or a certificate that never arrives:
placeholder domains, emails or secrets left in `.env` or the Traefik files, a
Traefik `Host()` rule that no longer matches `WEBAUTHN_RP_ID`, TLS skipped or a
bring-your-own certificate not in place, the domain not resolving to this host,
something else already on 80/443, and the five host prerequisites. Each `FAIL`
names its fix; it changes nothing and exits non-zero on any `FAIL`. A `warn`
is something it cannot decide from here — DNS pointing at a router's public
address is right behind NAT — and does not fail it. Run it any time: after an
upgrade, after a domain change, or paste its output into a bug report.

`KENDO_IMAGE` in `.env` is the pin. The documented default is the **Release
line** tag `:0.1`: fixes and features, but no Breaking change — nothing that
needs a manual step or a restore from backup to undo. Moving to `:0.2` is a
deliberate edit, made after reading its section in [Upgrading](upgrading.md).
From 1.0 the pin is the major, `:1` (ADR-0009).

Contributors still build from source — `make build` produces
`localhost/kendodojo:latest`; set `KENDO_IMAGE=localhost/kendodojo:latest` to
run it.

Traefik serves the app on 443 and redirects 80 to it. The `app` service
publishes no host port of its own: every request arrives through the proxy,
which is what makes `TRUST_PROXY_XFF` (on by default here) safe — Traefik
overwrites `X-Forwarded-For` with the address it observed, so rate limiting and
account lockout see a client IP the client cannot choose. If you re-publish the
app's port, set `TRUST_PROXY_XFF=false` in the same edit.

Alembic migrations run in the `migrate` service, which runs `alembic upgrade
head` and exits; `app` starts only once it has succeeded.
Uploaded logos and backgrounds persist in the `static_uploads` named volume, and
the database in `postgres_data` — both survive `down`/`up` and image rebuilds.
