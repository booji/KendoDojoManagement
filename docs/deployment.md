# Hardened deployment

What an operator graduates to from the [Quick self-host](install/quick-self-host.md): a hardened, self-hosted deployment on **rootless Podman + Quadlet**, fronted by **Traefik** for automatic HTTPS. Primary target: **AlmaLinux 10** (Podman 5.x). A Debian/Ubuntu stub is at the end.

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

### 1.0 Encrypt the disk

The Postgres data volume, the uploads volume and the local backups all sit on this host's disk and hold every Member's personal data, including under-18 and safeguarding data. Use full-disk encryption, so a stolen disk, a copied VM snapshot or a decommissioned drive gives none of it away:

- **Your own hardware or hypervisor:** choose LUKS ("Encrypt my data" in the AlmaLinux installer) when installing the OS; adding it later means a reinstall. The host then waits for the passphrase at every boot. For unattended reboots, bind it to the TPM with Clevis.
- **Cloud VM:** turn on the provider's encrypted volumes for the boot disk and any data disks.

This protects the disk while it is powered off, not a running host. Backups leave the disk, so they carry their own encryption: see [The backup key](install/backups.md#the-backup-key) and [Off-site copies](install/backups.md#off-site-copies-optional).

### 1.1 Install Podman

```bash
sudo dnf install -y podman   # AlmaLinux 10 ships Podman 5.x
podman --version             # confirm >= 4.4 (Quadlet); 5.x expected
```

### 1.2 Allow rootless binding of ports 80/443

Rootless containers can't bind ports <1024 by default. Write the one-line sysctl drop-in:

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-kendo-rootless-ports.conf
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
sudo machinectl shell kendo@ /bin/bash
# You are now kendo, with a working user systemd session.
```

Name the shell: `kendo`'s login shell is `nologin`, so it can never be logged
into directly, and without one `machinectl shell` ends at once with *This
account is currently not available*.

Everything from here (sections 2–6) runs **as `kendo` via `machinectl shell`**.

---

## 2-4. Lay it all down (as `kendo`)

```bash
# Extract the deployment bundle from the release image — no clone, no build.
# The bundle ships inside the image it configures, so the units below and the
# app they start are one artefact (ADR-0004).
mkdir -p ~/src && cd ~/src
podman run --rm ghcr.io/booji/kendodojomanagement:0.1 init | tar -x

./setup.sh --quadlet
```

`setup.sh --quadlet` asks for the domain, the TLS option and the ACME
challenge, then does every mechanical step that used to be three sections of
transcription here:

- **the six secrets** — `kendo_postgres_password`,
  `kendo_migration_database_url`, `kendo_database_url`, `kendo_jwt_secret`,
  `kendo_setup_token`, and the DNS-provider token when DNS-01 is chosen.
  `kendo_migration_database_url` is the superuser's login and has to embed the
  same password as `kendo_postgres_password`; one script generating both cannot
  mismatch them. `kendo_database_url` is the app's own login, `kendo_app`, which
  can only read and write rows
  ([ADR-0007](adr/0007-the-app-connects-as-a-least-privilege-database-user.md)):
  `kendo-migrate` is the only unit given the superuser, and it creates
  `kendo_app` and sets its password from the secret on every start. A re-run
  keeps every existing secret rather than rotating it.
- **the `~/kendo/` tree** — `kendo-app.env` with your domain in all three
  passkey-bound settings, `traefik/traefik.yml` with your ACME email and the
  challenge you picked, `traefik/dynamic/kendo.yml` with your `Host()` rule.
  Plus `~/backups` and the backup/restore scripts in `~/.local/bin`.
- **the Quadlet units** — copied into `~/.config/containers/systemd/`, pinned
  to the tag the bundle was extracted from, then `systemctl --user
  daemon-reload`. Plus `kendo-ip-retention.timer` and `kendo-backup.timer` in
  `~/.config/systemd/user/`, enabled — see [IP retention](#ip-retention) below
  and [Backups](install/backups.md).

It never escalates: the host prerequisites from section 1 are detected and the
exact `sudo` command printed for you to run from your admin account (`kendo`
has no sudo). Run as `kendo`, it cannot read the firewall rules either, so it
asks you to check those yourself rather than failing.

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

# 3. The superuser's login, for kendo-migrate only (must embed the SAME
#    password as #1)
printf '%s' 'postgresql+asyncpg://kendo:REPLACE-with-strong-db-password@kendo-db:5432/kendo' \
  | podman secret create kendo_migration_database_url -

# 4. The app's own login (ADR-0007), with a DIFFERENT password. kendo-migrate
#    creates the kendo_app user and sets its password from this.
printf '%s' 'postgresql+asyncpg://kendo_app:REPLACE-with-another-strong-password@kendo-db:5432/kendo' \
  | podman secret create kendo_database_url -

# 5. Setup token — gates claiming the first admin account (ADR-0003). Create it
#    BEFORE first boot: the app refuses to start without it, and whoever holds
#    it is who can claim admin.
openssl rand -base64 32 | tr -d '\n' \
  | podman secret create kendo_setup_token -
```

A sixth, `kendo_dns_token`, only when you use DNS-01 — with the drop-in from §5.

The units mount each secret as a file under `/run/secrets`, readable only by
the app's user, and tell the app where it is with `<NAME>_FILE` (for example
`JWT_SECRET_FILE=/run/secrets/jwt_secret`). None is passed as an environment
variable, so none shows up in `podman inspect` or is inherited by a process
the app starts (#462).

Then the units:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kendo-*.network   ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.volume    ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.container ~/.config/containers/systemd/

# Quadlet generates systemd units from these files on daemon-reload.
systemctl --user daemon-reload

# Quadlet generates no timers, so the daily IP-retention trigger and the
# nightly backup are plain user units (see IP retention below).
mkdir -p ~/.config/systemd/user
cp deploy/systemd/kendo-ip-retention.timer ~/.config/systemd/user/
cp deploy/systemd/kendo-backup.service deploy/systemd/kendo-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kendo-ip-retention.timer kendo-backup.timer
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

To rotate a secret later: `podman secret rm <name>` then recreate, and `systemctl --user restart` the affected unit. For `kendo_database_url` that is `kendo-migrate kendo-app`: the migration step is what sets the app user's new password, and restarting `kendo-app` alone does not re-run it.

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

### IP retention

`recovery_attempts` stores the IP address of each recovery-code attempt, and
the app clears it to NULL once the row is 30 days old (#434). `kendo-app` does
that on every start; `kendo-ip-retention.timer` runs `kendo-ip-retention.service`
(`python -m app.cli clear-expired-ip-addresses`, then exits) daily, so the
limit holds on an instance that is never restarted. `Persistent=true` catches up
a run missed while the host was off. `./setup.sh check --quadlet` fails while
the timer is not installed or not enabled.

```bash
systemctl --user list-timers kendo-ip-retention.timer --no-pager
systemctl --user status kendo-ip-retention --no-pager   # the last run
```

The Compose stack has no timer: there the clear runs only when the app starts.


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

## 8. Container limits

`kendo-app`, `kendo-migrate`, `kendo-ip-retention` and `kendo-traefik` assume they may be breached (#458): a read-only root filesystem (`/tmp` and the volumes are the only writable paths), every capability dropped (Traefik keeps `NET_BIND_SERVICE` for 80/443), `NoNewPrivileges=true`, and a cap of 256 pids and 512 MiB memory each. `kendo-db` is not hardened yet.

The limits are fixed defaults in the units. To change one on a small or busy host, add a drop-in. A later `PodmanArgs=` flag wins over the unit's own, and the drop-in survives re-copying the unit on upgrade:

```bash
d=~/.config/containers/systemd/kendo-app.container.d && mkdir -p "$d"
printf '[Container]\nPodmanArgs=--memory=1g --pids-limit=512\n' > "$d/30-limits.conf"
systemctl --user daemon-reload && systemctl --user restart kendo-app
```

The Compose stack carries the same settings (`x-hardening` in `docker-compose.yml`). There, set `mem_limit:` or `pids_limit:` on the service itself, which wins over the merged defaults.

## 9. Logs

The app writes its logs to the container's stdout. Podman's default `journald`
log driver hands them to the `kendo` user's journal, tagged with the
`kendo-app` unit, so the journal on the device is where they live. Nothing is
written to a log file inside the container (the root filesystem is read-only).

```bash
podman logs kendo-app                    # this container's output since it started
journalctl --user-unit kendo-app         # the unit's history, across restarts
```

Use `--user-unit`, not `--user -u`. `--user` reads only the per-user journal
file, which journald creates only when journal storage is persistent. On a host
without it, everything is in the system journal and `--user -u` shows nothing.
`--user-unit` works either way.

### Security events

Sign-ins, recovery, passkey and invite changes, the setup claim and the other
security events are one JSON object per line:

```json
{"timestamp":"2026-10-30T21:31:58.723232+00:00","event_type":"setup_claim","result":"success"}
```

`timestamp` (UTC, ISO 8601), `event_type` and `result` are always there.
`user_id`, `ip_address` and `detail` appear when they apply; every event raised
while serving a request carries the client's `ip_address`.

Sign-in and account events, with `result` `success` or `failure`:

| `event_type` | When |
|---|---|
| `login_passkey` | someone signs in with a passkey |
| `passkey_registered` | an Account adds a passkey |
| `passkey_deleted` | an Account removes a passkey |
| `recovery_redeem` | someone redeems a recovery code or admin recovery token |
| `admin_token_generated` | an Admin mints a recovery token for a Member (`detail` names the target) |
| `invite_minted` | an Admin creates an invite |
| `invite_revoked` | an Admin revokes an invite |
| `invite_redeemed` | someone redeems an invite |
| `setup_claim` | someone claims the first Admin Account with the `SETUP_TOKEN` |
| `sign_out_everywhere` | an Account signs out of every session |

Admin writes and exports are logged too, with the Admin as `user_id`:

| `event_type` | When | `detail` |
|---|---|---|
| `member_created` | an Admin adds a Member | `member_id` |
| `member_updated` | an Admin edits a Member, including changing their status (deactivation, archiving) | `member_id`, `changed_fields` |
| `member_erased` | an Admin erases a Member | `member_id` |
| `dojo_settings_updated` | an Admin changes dojo settings, or uploads a logo or login background | `changed_fields` |
| `report_exported` | an Admin downloads a CSV report | `report`, and `date_from` / `date_to` for attendance |

`changed_fields` lists field names only. The values, old or new, are never
logged. Reading data is not logged.

To see only these lines:

```bash
journalctl --user-unit kendo-app -o cat --grep '"event_type"'
# or pretty-print them, if jq is installed
journalctl --user-unit kendo-app -o cat --grep '"event_type"' | jq .
```

### How long they survive

journald decides, not the app. Check two things as an admin user:

- **Storage is persistent.** If `/var/log/journal` does not exist, the journal
  lives in `/run` and every event is gone at reboot. Create it with
  `sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald`,
  or set `Storage=persistent` in `/etc/systemd/journald.conf`.
- **Size caps.** `SystemMaxUse` and `SystemMaxFileSize` in
  `/etc/systemd/journald.conf` bound the journal's disk use. When the cap is
  hit the oldest entries go first, so on a small or busy disk events can
  vanish sooner than you expect. Check with `journalctl --disk-usage`.

Events carry client IP addresses, which are personal data, so keep them no
longer than you need. The app clears IPs from its own recovery-attempt records
after 30 days; matching that in the journal is a drop-in:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nMaxRetentionSec=30day\n' | sudo tee /etc/systemd/journald.conf.d/30-retention.conf
sudo systemctl restart systemd-journald
```

`MaxRetentionSec` is host-wide: it applies to every service's logs, not just
`kendo-app`.

### Collecting them off the host

Optional. Any collector that reads the journal works, and the app needs no
configuration for it: for example [Grafana Alloy](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/)
into Loki, [Graylog](https://go2docs.graylog.org/current/getting_in_log_data/ingest_journald.html),
or [`systemd-journal-remote`](https://www.freedesktop.org/software/systemd/man/latest/systemd-journal-remote.service.html).

The limit to be honest about: anyone who controls the host can delete events
the collector has not pulled yet. Pulling often keeps that window small; it
does not close it.

---

## Appendix — Debian / Ubuntu stub (not the primary target)

The above is written for AlmaLinux 10. On Debian/Ubuntu the shape is identical; the differences:

- **Podman version.** Debian 12 ships Podman **4.3** — too old for Quadlet. Install ≥4.4 from the [Kubic/OCI repo](https://build.opensuse.org/package/show/devel:kubic:libcontainers:stable/podman) or use Ubuntu 24.04 (Podman 4.9). Ubuntu 24.10+/newer is smoother.
- **No SELinux** (AppArmor instead) — the `:Z` volume labels are harmless no-ops; leave them.
- **Low ports / firewall.** `net.ipv4.ip_unprivileged_port_start` works the same via `/etc/sysctl.d/`. Use `ufw` instead of `firewalld` for the redirect alternative.
- **User/linger/machinectl** — `useradd`, `loginctl enable-linger`, and `machinectl shell` all work identically (systemd-based).

> TODO (future): validate and expand this section against a real Debian/Ubuntu host, and consider a GHCR-published image so these hosts skip the build toolchain.
