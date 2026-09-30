# Deploying KendoDojoManagement to UAT / PROD

Production-grade, self-hosted deployment on **rootless Podman + Quadlet**, fronted by **Traefik** for automatic HTTPS. Primary target: **AlmaLinux 10** (Podman 5.x). A Debian/Ubuntu stub is at the end.

> **Architecture at a glance.** The app image serves both the built SPA and the `/api` from one FastAPI container on port 8000. Three containers run per host:
>
> ```
>            :80/:443 (host)
>                │
>          ┌─────▼─────┐        kendo-edge (external)
>          │  traefik  │◄───────────────┐
>          └───────────┘                │
>                                  ┌─────▼─────┐   kendo-backend (isolated)
>                                  │    app    │◄──────────────┐
>                                  └───────────┘               │
>                                                        ┌──────▼─────┐
>                                                        │  postgres  │
>                                                        └────────────┘
> ```
>
> - **`kendo-edge`** — Traefik ↔ app. Traefik is the only container publishing host ports.
> - **`kendo-backend`** — app ↔ db, no host ports. The db lives only here, so nothing outside this network can reach it.
> - Both networks set `Options=isolate=true`, which blocks traffic to containers on other Podman networks while leaving internet egress intact (Traefik still reaches Let's Encrypt).
> - The app straddles both networks; the db is reachable only from the app.

All artifacts referenced below live in [`deploy/`](https://github.com/booji/KendoDojoManagement/tree/main/deploy).

UAT and PROD are **separate hosts, one instance each**. The Quadlet units, Traefik config, and scripts are identical between them — only the per-host env file values and secrets differ.

---

## 1. One-time host preparation (as an admin / sudo user)

### 1.1 Install Podman

```bash
sudo dnf install -y podman   # AlmaLinux 10 ships Podman 5.x
podman --version             # confirm >= 4.4 (Quadlet); 5.x expected
```

### 1.2 Allow rootless binding of ports 80/443

Rootless containers can't bind ports <1024 by default. Install the provided sysctl drop-in:

```bash
sudo install -m 0644 deploy/sysctl-99-kendo-rootless-ports.conf \
  /etc/sysctl.d/99-kendo-rootless-ports.conf
sudo sysctl --system
```

> **Trade-off:** any unprivileged process may now bind ports ≥80 — fine on a single-purpose appliance. **Hardened alternative** (keeps the <1024 restriction): leave the sysctl out, set Traefik to publish `8080:80`/`8443:443`, and add a firewalld redirect:
> ```bash
> sudo firewall-cmd --permanent --add-forward-port=port=443:proto=tcp:toport=8443
> sudo firewall-cmd --permanent --add-forward-port=port=80:proto=tcp:toport=8080
> sudo firewall-cmd --reload
> ```

### 1.3 Open the firewall

```bash
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
```

### 1.4 Create the dedicated rootless user `kendo`

A no-login system account owns and runs every container. It is **never** in `sudo`/`wheel` and is never logged into directly.

```bash
sudo useradd --create-home --shell /usr/sbin/nologin kendo
# Verify subuid/subgid ranges exist (auto on AlmaLinux 10); add if missing:
grep -q '^kendo:' /etc/subuid || echo "kendo:200000:65536" | sudo tee -a /etc/subuid
grep -q '^kendo:' /etc/subgid || echo "kendo:200000:65536" | sudo tee -a /etc/subgid

# Linger: start the kendo user manager at boot, keep services running with
# nobody logged in.
sudo loginctl enable-linger kendo
```

### 1.5 Get an admin shell as `kendo`

Always use `machinectl` — it sets up a proper session bus and `XDG_RUNTIME_DIR`, so `systemctl --user` works. (`su - kendo` does **not** and will leave `systemctl --user` broken.)

```bash
sudo machinectl shell kendo@
# You are now kendo, with a working user systemd session.
```

Everything from here (sections 2–6) runs **as `kendo` via `machinectl shell`**.

---

## 2-4. Lay it all down (as `kendo`)

```bash
# Extract the deployment bundle from the release image — no clone, no build.
# The bundle ships inside the image it configures, so the units below and the
# app they start are one artefact (ADR-0004).
mkdir -p ~/src && cd ~/src
podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x

./setup.sh --quadlet
```

`setup.sh --quadlet` asks for the domain, the TLS option and the ACME
challenge, then does every mechanical step that used to be three sections of
transcription here:

- **the five secrets** — `kendo_postgres_password`, `kendo_jwt_secret`,
  `kendo_database_url`, `kendo_setup_token`, and the DNS-provider token when
  DNS-01 is chosen. `kendo_database_url` has to embed the same password as
  `kendo_postgres_password`; one script generating both cannot mismatch them.
  A re-run keeps every existing secret rather than rotating it.
- **the `~/kendo/` tree** — `kendo-app.env` with your domain in all three
  passkey-bound settings, `traefik/traefik.yml` with your ACME email and the
  challenge you picked, `traefik/dynamic/kendo.yml` with your `Host()` rule.
  Plus `~/backups` and the backup/restore scripts in `~/.local/bin`.
- **the Quadlet units** — copied into `~/.config/containers/systemd/`, pinned
  to the tag the bundle was extracted from, then `systemctl --user
  daemon-reload`.

It never escalates: the host prerequisites from section 1 are detected and the
exact `sudo` command printed for you to run.

`./setup.sh check --quadlet` is the preflight, and is safe to run at any time —
after an upgrade, after a domain change, or pasted into a bug report. It checks
what the app cannot see from inside its container: placeholders left in
`~/kendo/`, the `Host()` rule against `WEBAUTHN_RP_ID`, the certificate the TLS
option needs, the podman secrets, DNS for the domain, whether 80/443 are
already taken, and the section 1 prerequisites. Every `FAIL` names its fix and
makes it exit non-zero; a `warn` (DNS resolving to a router's public address
behind NAT, say) is informational. It changes nothing and gates nothing — the
app still guards its own configuration at startup.

**The setup token is printed once.** A podman secret cannot be read back, so
the value that claims the first admin account (ADR-0003) is shown at the end of
the run and nowhere else. Lost means rotate (below), not recover.

Then check, and start the stack:

```bash
./setup.sh check --quadlet                     # green? then:
systemctl --user start kendo-traefik.service   # Requires= pulls in app -> migrate -> db
systemctl --user status kendo-db kendo-migrate kendo-app kendo-traefik --no-pager
podman ps
```

<details>
<summary>By hand, without <code>setup.sh</code></summary>

```bash
# Config tree the Quadlet units expect at ~/kendo/
mkdir -p ~/kendo/traefik/dynamic ~/backups ~/.local/bin
cp deploy/traefik/traefik.yml            ~/kendo/traefik/traefik.yml
cp deploy/traefik/dynamic/kendo.yml      ~/kendo/traefik/dynamic/kendo.yml
cp deploy/env/kendo-app.env.example      ~/kendo/kendo-app.env
cp deploy/bin/kendo-backup.sh            ~/.local/bin/ && chmod +x ~/.local/bin/kendo-backup.sh
cp deploy/bin/kendo-restore.sh           ~/.local/bin/ && chmod +x ~/.local/bin/kendo-restore.sh
```

Then edit the placeholders:

- `~/kendo/kendo-app.env` — set `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `CORS_ORIGINS` to your real domain. Leave `TRUST_PROXY_XFF=true` (required behind Traefik — see §6).
- `~/kendo/traefik/traefik.yml` — set the ACME `email`, and swap the challenge if HTTP-01 does not suit (§5).
- `~/kendo/traefik/dynamic/kendo.yml` — set the `Host(...)` rule to your domain.

The secrets. These never touch a plaintext env file. Generate strong values and
pipe them in (avoid leaving them in shell history — note the leading space or
use `read`):

```bash
# 1. Postgres password
printf '%s' 'REPLACE-with-strong-db-password' | podman secret create kendo_postgres_password -

# 2. JWT secret
python3 -c "import secrets; print(secrets.token_hex(32))" | tr -d '\n' \
  | podman secret create kendo_jwt_secret -

# 3. Full DATABASE_URL (must embed the SAME password as #1)
printf '%s' 'postgresql+asyncpg://kendo:REPLACE-with-strong-db-password@kendo-db:5432/kendo' \
  | podman secret create kendo_database_url -

# 4. Setup token — gates claiming the first admin account (ADR-0003). Create it
#    BEFORE first boot: the app refuses to start without it, and whoever holds
#    it is who can claim admin.
openssl rand -base64 32 | tr -d '\n' \
  | podman secret create kendo_setup_token -
```

A fifth, `kendo_dns_token`, only when you use DNS-01 — with the drop-in from §5.

Then the units:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kendo-*.network   ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.volume    ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.container ~/.config/containers/systemd/

# Quadlet generates systemd units from these files on daemon-reload.
systemctl --user daemon-reload
```

</details>

> The DB host in `DATABASE_URL` is `kendo-db` — the container name, resolved by Podman's DNS on the `kendo-backend` network.
>
> This is why that network uses `Options=isolate=true` rather than `Internal=true`
> (#281): Podman disables DNS on internal networks, so `kendo-db` would not
> resolve and `kendo-app` could never connect. `isolate=true` keeps DNS while
> still blocking cross-network traffic by IP. The trade is that the database
> keeps an outbound route; on Podman that cannot be removed without also losing
> name resolution.

To rotate a secret later: `podman secret rm <name>` then recreate, and `systemctl --user restart` the affected unit.

Because the user has **linger** enabled and the units declare `WantedBy=default.target`, the stack now starts automatically on boot. No `enable` step is needed for `.container` units generated by Quadlet — the `[Install]` section handles it after `daemon-reload`.

Watch the first cert issuance:

```bash
podman logs -f kendo-traefik   # look for successful ACME / certificate obtained
```

Migrations run as their own unit: `kendo-migrate.service` runs `alembic
upgrade head` and exits, and `kendo-app` is ordered after it, so the app
never serves against a half-migrated schema and a failed migration shows up
as a failed `kendo-migrate.service` rather than as an app crash (#391).
`systemctl --user status kendo-migrate --no-pager` shows the last run.


## 5. TLS options

`setup.sh --quadlet` asks this question and writes the answer; this section is
what it writes, for a deployment configured by hand or changed later.

- **HTTP-01 (default).** Needs inbound port 80. Nothing beyond the `httpChallenge` block already in `traefik.yml`.
- **TLS-ALPN-01.** Inbound 443 only — the answer when an ISP blocks 80. Replace the `httpChallenge` block with `tlsChallenge: {}`.
- **DNS-01.** No inbound ports at all (e.g. UAT on a local network). Replace the `httpChallenge` block with a `dnsChallenge` naming your [lego provider](https://go-acme.github.io/lego/dns/), and give Traefik the credentials as a drop-in — the unit itself stays provider-neutral, and a drop-in survives re-copying the unit on upgrade:

  ```bash
  printf '%s' 'REPLACE-with-provider-token' | podman secret create kendo_dns_token -
  d=~/.config/containers/systemd/kendo-traefik.container.d && mkdir -p "$d"
  printf '[Container]\nEnvironment=CF_DNS_API_TOKEN_FILE=/run/secrets/dns_token\nSecret=kendo_dns_token,type=mount,target=dns_token\n' > "$d/10-dns-01.conf"
  systemctl --user daemon-reload && systemctl --user restart kendo-traefik
  ```

  `CF_DNS_API_TOKEN` is Cloudflare's variable (scope the token to `Zone:DNS:Edit` on one zone); use whichever your provider documents. A provider that needs several variables needs one `Environment=`/`Secret=` pair each.
- **Bring-your-own cert (internal CA / purchased wildcard).** For hosts that can't use Let's Encrypt. See [`deploy/traefik/dynamic/byo-cert.yml.example`](https://github.com/booji/KendoDojoManagement/blob/main/deploy/traefik/dynamic/byo-cert.yml.example) — it documents the `certs/` bind mount (with the required `:Z` SELinux label) and the router change. `setup.sh --quadlet` writes both, the mount as a `20-byo-cert.conf` drop-in; the cert and key are yours to drop in `~/kendo/traefik/certs/`.

---

## 6. Why `TRUST_PROXY_XFF=true` is required behind Traefik

With Traefik in front, every request's peer IP is Traefik's container IP. The app's rate limiting is keyed on client IP — left unadjusted every visitor shares one bucket, so a single busy client exhausts the limit for everyone. Setting `TRUST_PROXY_XFF=true` makes the app read the real client IP from `X-Forwarded-For`.

This is the only rate limiting in the deployment: Traefik's dynamic config carries a `security-headers` middleware and no `RateLimit`.

This is safe **only because** of the network design: the app publishes no host ports and is reachable solely through Traefik, which overwrites any client-supplied `X-Forwarded-For` (do **not** enable `forwardedHeaders.insecure` on Traefik's entrypoints). The flag defaults to `false` so local dev — where the app is directly reachable — stays spoof-proof.

## 7. A note on CORS

The SPA is served **same-origin** with the API (both under `https://<your-domain>`), so CORS never fires in normal operation. Keep `CORS_ORIGINS` pinned to the single canonical origin (never `*`) — auth is cookie-based, and `*` + credentials is both invalid and a credential-leak risk. Pinning means any accidental cross-origin path fails closed.

---


---

## Appendix — Debian / Ubuntu stub (not the primary target)

The above is written for AlmaLinux 10. On Debian/Ubuntu the shape is identical; the differences:

- **Podman version.** Debian 12 ships Podman **4.3** — too old for Quadlet. Install ≥4.4 from the [Kubic/OCI repo](https://build.opensuse.org/package/show/devel:kubic:libcontainers:stable/podman) or use Ubuntu 24.04 (Podman 4.9). Ubuntu 24.10+/newer is smoother.
- **No SELinux** (AppArmor instead) — the `:Z` volume labels are harmless no-ops; leave them.
- **Low ports / firewall.** `net.ipv4.ip_unprivileged_port_start` works the same via `/etc/sysctl.d/`. Use `ufw` instead of `firewalld` for the redirect alternative.
- **User/linger/machinectl** — `useradd`, `loginctl enable-linger`, and `machinectl shell` all work identically (systemd-based).

> TODO (future): validate and expand this section against a real Debian/Ubuntu host, and consider a GHCR-published image so these hosts skip the build toolchain.
