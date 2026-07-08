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
>                                  ┌─────▼─────┐   kendo-backend (internal)
>                                  │    app    │◄──────────────┐
>                                  └───────────┘               │
>                                                        ┌──────▼─────┐
>                                                        │  postgres  │
>                                                        └────────────┘
> ```
>
> - **`kendo-edge`** — Traefik ↔ app. Traefik is the only container publishing host ports.
> - **`kendo-backend`** — app ↔ db, **internal** (no outbound, no host ports). The db lives only here, so nothing outside can reach it.
> - The app straddles both networks; the db is fully isolated.

All artifacts referenced below live in [`deploy/`](../deploy).

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

## 2. Lay down the application files (as `kendo`)

```bash
# Build the image from source (build-on-host model).
git clone https://github.com/booji/KendoDojoManagement.git ~/src
cd ~/src
podman build -t localhost/kendodojo:latest .

# Config tree the Quadlet units expect at ~/kendo/
mkdir -p ~/kendo/traefik/dynamic ~/backups ~/.local/bin
cp deploy/traefik/traefik.yml            ~/kendo/traefik/traefik.yml
cp deploy/traefik/dynamic/kendo.yml      ~/kendo/traefik/dynamic/kendo.yml
cp deploy/env/kendo-app.env.example      ~/kendo/kendo-app.env
cp deploy/bin/kendo-backup.sh            ~/.local/bin/ && chmod +x ~/.local/bin/kendo-backup.sh
cp deploy/bin/kendo-restore.sh           ~/.local/bin/ && chmod +x ~/.local/bin/kendo-restore.sh
```

Now **edit the placeholders**:

- `~/kendo/kendo-app.env` — set `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `CORS_ORIGINS` to your real domain. Leave `TRUST_PROXY_XFF=true` (required behind Traefik — see §7).
- `~/kendo/traefik/traefik.yml` — set the ACME `email`.
- `~/kendo/traefik/dynamic/kendo.yml` — set the `Host(...)` rule to your domain.

---

## 3. Create the secrets (as `kendo`)

Three sensitive values never touch a plaintext env file — they are Podman secrets. Generate strong values and pipe them in (avoid leaving them in shell history — note the leading space or use `read`):

```bash
# 1. Postgres password
printf '%s' 'REPLACE-with-strong-db-password' | podman secret create kendo_postgres_password -

# 2. JWT secret
python3 -c "import secrets; print(secrets.token_hex(32))" | tr -d '\n' \
  | podman secret create kendo_jwt_secret -

# 3. Full DATABASE_URL (must embed the SAME password as #1)
printf '%s' 'postgresql+asyncpg://kendo:REPLACE-with-strong-db-password@kendo-db:5432/kendo' \
  | podman secret create kendo_database_url -

# 4. Cloudflare API token (DNS-01). Scope it to Zone:DNS:Edit on ONE zone only.
printf '%s' 'REPLACE-with-cloudflare-token' | podman secret create kendo_cf_dns_token -
```

> The DB host in `DATABASE_URL` is `kendo-db` — the container name, resolvable on the `kendo-backend` network.

To rotate a secret later: `podman secret rm <name>` then recreate, and `systemctl --user restart` the affected unit.

---

## 4. Install and start the Quadlet units (as `kendo`)

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kendo-*.network   ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.volume    ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.container ~/.config/containers/systemd/

# Quadlet generates systemd units from these files on daemon-reload.
systemctl --user daemon-reload

# Networks/volumes come up as dependencies of the containers. Start the stack:
systemctl --user start kendo-traefik.service   # pulls in app -> db via Requires=

# Check status
systemctl --user status kendo-db kendo-app kendo-traefik --no-pager
podman ps
```

Because the user has **linger** enabled and the units declare `WantedBy=default.target`, the stack now starts automatically on boot. No `enable` step is needed for `.container` units generated by Quadlet — the `[Install]` section handles it after `daemon-reload`.

Watch the first cert issuance:

```bash
podman logs -f kendo-traefik   # look for successful ACME / certificate obtained
```

Migrations run automatically on app startup (`entrypoint.sh` → `alembic upgrade head`).

---

## 5. TLS options

The shipped config uses **Let's Encrypt via Cloudflare DNS-01** — works even with no inbound port 80 (e.g. UAT on a local network). It only needs port 443 reachable (LAN for UAT, internet for PROD).

- **DNS-01 / Cloudflare (default, active).** Requires the `kendo_cf_dns_token` secret. Nothing else to do.
- **HTTP-01 (public host with inbound port 80).** In `traefik.yml`, comment out the `dnsChallenge` block and uncomment `httpChallenge`. Drop the Cloudflare secret if unused.
- **Bring-your-own cert (internal CA / purchased wildcard).** For hosts that can't use Let's Encrypt. See [`deploy/traefik/dynamic/byo-cert.yml.example`](../deploy/traefik/dynamic/byo-cert.yml.example) — it documents the `certs/` bind mount (with the required `:Z` SELinux label) and the router change.

---

## 6. Backups (as `kendo`)

Nightly `pg_dump` (custom format) to `~/backups`, keeping the newest 14, driven by a systemd user timer.

```bash
cp deploy/systemd/kendo-backup.service ~/.config/systemd/user/
cp deploy/systemd/kendo-backup.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kendo-backup.timer

# Verify schedule + run once now
systemctl --user list-timers kendo-backup.timer --no-pager
systemctl --user start kendo-backup.service
ls -lh ~/backups
```

**Restore** (destructive — stops writes, drops/recreates the DB):

```bash
systemctl --user stop kendo-app
~/.local/bin/kendo-restore.sh ~/backups/kendo-YYYYmmdd-HHMMSS.dump
systemctl --user start kendo-app
```

> **Copy backups off-box.** A dump on the same host does not survive host loss. Ship `~/backups` elsewhere (rsync/restic/object storage) — not implemented here.

---

## 7. Why `TRUST_PROXY_XFF=true` is required behind Traefik

With Traefik in front, every request's peer IP is Traefik's container IP. The app's rate limiting **and** account lockout are keyed on client IP — left unadjusted they would collapse into a single global bucket (one attacker could lock out everyone). Setting `TRUST_PROXY_XFF=true` makes the app read the real client IP from `X-Forwarded-For`.

This is safe **only because** of the network design: the app publishes no host ports and is reachable solely through Traefik, which overwrites any client-supplied `X-Forwarded-For` (do **not** enable `forwardedHeaders.insecure` on Traefik's entrypoints). The flag defaults to `false` so local dev — where the app is directly reachable — stays spoof-proof.

## 8. A note on CORS

The SPA is served **same-origin** with the API (both under `https://<your-domain>`), so CORS never fires in normal operation. Keep `CORS_ORIGINS` pinned to the single canonical origin (never `*`) — auth is cookie-based, and `*` + credentials is both invalid and a credential-leak risk. Pinning means any accidental cross-origin path fails closed.

---

## 9. Day-2 operations

| Task | Command (as `kendo` via `machinectl shell kendo@`) |
|------|----|
| Status | `systemctl --user status kendo-app --no-pager` |
| Logs | `podman logs -f kendo-app` |
| Restart app | `systemctl --user restart kendo-app` |
| **Upgrade** | `cd ~/src && git pull && podman build -t localhost/kendodojo:latest . && systemctl --user restart kendo-app` |
| Stop all | `systemctl --user stop kendo-traefik kendo-app kendo-db` |
| Break-glass recovery | `podman exec kendo-app python -m app.cli create-recovery-token <email>` |

---

## Appendix — Debian / Ubuntu stub (not the primary target)

The above is written for AlmaLinux 10. On Debian/Ubuntu the shape is identical; the differences:

- **Podman version.** Debian 12 ships Podman **4.3** — too old for Quadlet. Install ≥4.4 from the [Kubic/OCI repo](https://build.opensuse.org/package/show/devel:kubic:libcontainers:stable/podman) or use Ubuntu 24.04 (Podman 4.9). Ubuntu 24.10+/newer is smoother.
- **No SELinux** (AppArmor instead) — the `:Z` volume labels are harmless no-ops; leave them.
- **Low ports / firewall.** `net.ipv4.ip_unprivileged_port_start` works the same via `/etc/sysctl.d/`. Use `ufw` instead of `firewalld` for the redirect alternative.
- **User/linger/machinectl** — `useradd`, `loginctl enable-linger`, and `machinectl shell` all work identically (systemd-based).

> TODO (future): validate and expand this section against a real Debian/Ubuntu host, and consider a GHCR-published image so these hosts skip the build toolchain.
