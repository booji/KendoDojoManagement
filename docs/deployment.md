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

- `~/kendo/kendo-app.env` — set `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `CORS_ORIGINS` to your real domain. Leave `TRUST_PROXY_XFF=true` (required behind Traefik — see §7).
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

### Claim the admin account (the setup token gates it)

The instance is now reachable. Claiming the first admin account requires the
`kendo_setup_token` secret from section 2-4 — the setup endpoints answer
`401 {"detail": "Invalid setup token"}` without it (ADR-0003). Nothing to race:
an opportunistic scanner that finds the host minutes after Traefik's Let's
Encrypt certificate hits the certificate transparency logs cannot claim
anything without that value.

The token is required whether or not the instance is already claimed: the app
refuses to start without it, so do not delete the secret after claiming. A
database restore or wipe would otherwise boot an unclaimed instance with no
gate in front of it.

**The browser is the way you do this.** Open `https://<your-domain>/`: the
setup page asks for the admin email and the setup token. Paste the token into
the "Setup token" field and complete the passkey registration. The page sends
it as an `X-Setup-Token` header on `/api/setup/passkey/begin` and
`/api/setup/passkey/complete`, and a wrong token comes back on the form as
"Invalid setup token". The value is never stored in the browser — reloading the
page means pasting it again.

No shell access is needed to claim the account, so the URL and the token can go
to whoever is becoming the admin. The `curl` below is for debugging a claim
that is not working, not a step:

```bash
curl -sS -X POST https://<your-domain>/api/setup/passkey/begin \
  -H 'Content-Type: application/json' \
  -H "X-Setup-Token: $SETUP_TOKEN" \
  -d '{"email":"admin@your-dojo"}'
# 401 {"detail":"Invalid setup token"} -> wrong or missing token.
# 404 {"detail":"Setup already completed"} -> claimed; the token is irrelevant.
```

Then confirm the window is shut.

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<your-domain>/api/setup
# 404 -> setup is closed, an account exists.
# 200 -> still unclaimed (the token is still required to claim it).
# anything else (000, 502, ...) -> the check never reached the app. That is not
# a closed window; fix the request and re-run before you believe it.
```

The claimed guard counts *passkey credentials*, not users: an abandoned
ceremony leaves a user row with no credential and deliberately does **not**
count, so an operator whose browser died mid-ceremony is never locked out.

**Lost the token?** Rotate it — nothing in the database has to change:

```bash
# Keep the value: a podman secret cannot be read back, so piping straight into
# `secret create` leaves you with a token nobody knows.
token=$(openssl rand -base64 32 | tr -d '\n')
podman secret rm kendo_setup_token
printf '%s' "$token" | podman secret create kendo_setup_token -
systemctl --user restart kendo-app
echo "$token"   # hand it over out of band, then clear your scrollback
```

`app/cli.py create-recovery-token` does **not** cover a never-claimed instance:
it resolves a `User` row by email, and an unclaimed instance has none. Rotation
is the only path there, and it costs seconds.

### Upgrading a deployment created before the Alembic baseline (issue #264)

As of issue #264, the Alembic chain has a baseline migration (`000000000000`)
that creates the full schema from nothing, so `alembic upgrade head` now
works against a genuinely empty database. This changes nothing for an
instance that was already deployed and running:

- **Any instance deployed before this change** already has an
  `alembic_version` row naming a revision at or after `a1b2c3d4e5f6` (every
  prior deploy got its schema from `Base.metadata.create_all` followed by
  `alembic stamp head` on first boot). Alembic walks forward from whatever
  revision is recorded in `alembic_version`; it does not replay or
  re-verify ancestors behind that revision. The new baseline is an ancestor
  of `a1b2c3d4e5f6` and is simply never visited. `alembic upgrade head`
  continues to work exactly as before — no action needed.
- **A legacy pre-Alembic instance** (tables exist, but there is no
  `alembic_version` table at all — only possible if the instance predates
  `a1b2c3d4e5f6` merging *and* has never restarted since; every restart
  under the pre-#264 bootstrap already ran `alembic upgrade head`
  unconditionally for a non-empty database, which creates
  `alembic_version` on its first successful migration) needs one manual
  step before its next `alembic upgrade head`:

  ```bash
  podman exec kendo-app alembic stamp head
  ```

  This is correct **only if you're confident the instance's schema matches
  the current ORM exactly** (i.e. it's been kept current) — the same
  assumption the pre-#264 bootstrap made for a "fresh" database
  (`create_all` then `stamp head`), and safe for the same reason:
  `test_migrated_schema_matches_orm_metadata_exactly` guarantees a
  `create_all` schema and a fully-migrated schema are identical at head.
  Do **not** stamp at `a1b2c3d4e5f6` or at the new baseline
  (`000000000000`) — either leaves `alembic_version` naming a revision
  *before* tables this instance's `create_all` already built (`federations`,
  `member_federations`, `invites`, and everything added after them), so the
  next `alembic upgrade head` tries to create things that already exist and
  fails.

  **If there's any doubt the schema is current** — the instance predates
  some migration that shipped after it was last redeployed — **no single
  stamp target is correct**, and guessing one will silently leave the
  database wrong (either missing real schema changes, or erroring out
  trying to redo ones it already has). Diff the live schema against
  `app.db.base.Base.metadata` first (e.g. via
  `alembic.autogenerate.compare_metadata`, the same check
  `test_migrated_schema_matches_orm_metadata_exactly` runs) to see exactly
  what's missing, then either apply those changes by hand and stamp head,
  or — safer — back up the data, run `alembic upgrade head` against a fresh
  empty database, and migrate the data across instead of reconciling the
  old schema in place. See the baseline migration's docstring
  (`backend/alembic/versions/000000000000_baseline_schema.py`) for the full
  reasoning.

---

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
- **Bring-your-own cert (internal CA / purchased wildcard).** For hosts that can't use Let's Encrypt. See [`deploy/traefik/dynamic/byo-cert.yml.example`](../deploy/traefik/dynamic/byo-cert.yml.example) — it documents the `certs/` bind mount (with the required `:Z` SELinux label) and the router change. `setup.sh --quadlet` writes both, the mount as a `20-byo-cert.conf` drop-in; the cert and key are yours to drop in `~/kendo/traefik/certs/`.

---

## 6. Backups (as `kendo`)

Nightly backup to `~/backups`, keeping the newest 14 of each artefact, driven by a systemd user timer. Each run writes two files sharing one timestamp:

| File | Contents |
| --- | --- |
| `kendo-<stamp>.dump` | Postgres, `pg_dump` custom format |
| `kendo-uploads-<stamp>.tar` | the `kendo-app-uploads` volume — logos and login backgrounds |

Uploaded images live on a volume, not in the database, so the dump alone does not cover them.

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
# Second argument is optional; pass the uploads tarball with the same timestamp
# to restore logos and backgrounds alongside the database.
~/.local/bin/kendo-restore.sh \
  ~/backups/kendo-YYYYmmdd-HHMMSS.dump \
  ~/backups/kendo-uploads-YYYYmmdd-HHMMSS.tar
systemctl --user start kendo-app
```

> **Copy backups off-box.** A dump on the same host does not survive host loss. Ship `~/backups` elsewhere (rsync/restic/object storage) — not implemented here.

---

## 7. Why `TRUST_PROXY_XFF=true` is required behind Traefik

With Traefik in front, every request's peer IP is Traefik's container IP. The app's rate limiting is keyed on client IP — left unadjusted every visitor shares one bucket, so a single busy client exhausts the limit for everyone. Setting `TRUST_PROXY_XFF=true` makes the app read the real client IP from `X-Forwarded-For`.

This is the only rate limiting in the deployment: Traefik's dynamic config carries a `security-headers` middleware and no `RateLimit`.

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
| **Upgrade** | `podman pull ghcr.io/booji/kendodojomanagement:1 && systemctl --user restart kendo-migrate kendo-app` |
| Stop all | `systemctl --user stop kendo-traefik kendo-app kendo-migrate kendo-db` |
| Break-glass recovery | `podman exec kendo-app python -m app.cli create-recovery-token <email>` |

> The pin is the `Image=` line in the two Quadlet units, and the documented
> value is the **major** tag `:1` — fixes and features, but no migration that
> needs a restore from backup to undo. Moving to `:2` is a deliberate edit made
> after reading the release notes. Building from source still works
> (`podman build -t localhost/kendodojo:latest .`); point `Image=` at it.
>
> **When a Quadlet unit, the Traefik config or the env file changes upstream**,
> the Upgrade command above is not enough — it pulls the image but reuses the
> units already in `~/.config/containers/systemd/`, the Traefik config already in
> `~/kendo/traefik/`, and it never touches `~/kendo/kendo-app.env`. Each is a
> copy made once at install time; pulling a new image updates neither.
>
> ```bash
> # Re-extract the bundle from the tag you are pinned to — it ships inside the
> # image, so the units below match the app they start.
> cd ~/src && podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x
>
> # Units: re-run the copy from §2-4, then daemon-reload so Quadlet regenerates.
> cp deploy/quadlet/kendo-*.network   ~/.config/containers/systemd/
> cp deploy/quadlet/kendo-*.volume    ~/.config/containers/systemd/
> cp deploy/quadlet/kendo-*.container ~/.config/containers/systemd/
> systemctl --user daemon-reload
>
> # Traefik dynamic config — keep your Host() rule, take the rest. Traefik
> # watches this directory, so no restart is needed once the file lands.
> diff deploy/traefik/dynamic/kendo.yml ~/kendo/traefik/dynamic/kendo.yml
>
> systemctl --user restart kendo-migrate kendo-app
> ```
>
> The env file is per-host and needs comparing rather than copying — see
> [§9.1](#91-refreshing-the-env-file-after-an-upgrade).
>
> **A host installed before #412 that uses DNS-01 needs the drop-in before its
> next unit refresh.** `kendo-traefik.container` used to hardcode
> `CF_DNS_API_TOKEN_FILE` and the `kendo_cf_dns_token` secret; it no longer
> does, so re-copying it leaves Traefik with no DNS credentials and ACME
> renewal fails. Write the drop-in from [§5](#5-tls-options) first — pointing
> `Secret=` at your existing `kendo_cf_dns_token` is fine, no new secret needed.
>
> **Hosts installed before #385 need the unit refresh now.** That change made
> the app run unprivileged and mounts the uploads volume `:U`; both live in
> `kendo-app.container`, so neither reaches an existing host until the copy
> above. The edge health check lives in the Traefik dynamic config.

---

### 9.1 Refreshing the env file after an upgrade

Re-extracting the bundle updates `deploy/env/kendo-app.env.example` in
`~/src`. It does not update `~/kendo/kendo-app.env` — that file is yours, per
host, and nothing overwrites it except a deliberate re-run of `./setup.sh
--quadlet`, which rewrites it from the example (keeping the previous one as
`kendo-app.env.bak`). That is the quickest way to pick up new keys, and it
discards any local edit beyond the three domain values, so compare the two
afterwards if you have any. When an upgrade adds a setting, the app silently runs without
it: the Quadlet unit passes this one `EnvironmentFile` and nothing else, so a
key absent from it is absent from the app's environment.

Compare **keys**, not lines. Values legitimately differ per host, so a plain
`diff` is all noise; the keys are what drift:

```bash
diff <(grep -oE '^[A-Z0-9_]+=' ~/kendo/kendo-app.env | tr -d = | sort) \
     <(grep -oE '^[A-Z0-9_]+=' ~/src/deploy/env/kendo-app.env.example | tr -d = | sort)
```

Empty output means nothing new upstream. A `>` line is a setting you are
missing — copy it across with its comment, then restart:

```bash
systemctl --user restart kendo-app
```

A changed `EnvironmentFile` needs only a restart; a changed *unit* file needs
re-copying and a `daemon-reload` first — the note under the table above has
that sequence.

Then verify the app actually received it — a restart proves the unit started,
not that the value arrived:

```bash
podman exec kendo-app printenv APP_ENV JWT_EXPIRE_MINUTES
# APP_ENV=production
# JWT_EXPIRE_MINUTES=480
```

> **Hosts deployed before #386 need this now.** That change added
> `APP_ENV=production` (without it the app takes its development path and skips
> every production WebAuthn check at startup) and raised
> `JWT_EXPIRE_MINUTES` to 480. Both live in the env file, so neither reaches an
> existing host until you copy them across.
>
> #387 adds `SESSION_MAX_MINUTES` (default 10080 — 7 days), the ceiling on a
> session that sliding renewal keeps alive. It defaults in `app/config.py`, so
> an existing host needs it in the env file only to override that default.

---

## Appendix — Debian / Ubuntu stub (not the primary target)

The above is written for AlmaLinux 10. On Debian/Ubuntu the shape is identical; the differences:

- **Podman version.** Debian 12 ships Podman **4.3** — too old for Quadlet. Install ≥4.4 from the [Kubic/OCI repo](https://build.opensuse.org/package/show/devel:kubic:libcontainers:stable/podman) or use Ubuntu 24.04 (Podman 4.9). Ubuntu 24.10+/newer is smoother.
- **No SELinux** (AppArmor instead) — the `:Z` volume labels are harmless no-ops; leave them.
- **Low ports / firewall.** `net.ipv4.ip_unprivileged_port_start` works the same via `/etc/sysctl.d/`. Use `ufw` instead of `firewalld` for the redirect alternative.
- **User/linger/machinectl** — `useradd`, `loginctl enable-linger`, and `machinectl shell` all work identically (systemd-based).

> TODO (future): validate and expand this section against a real Debian/Ubuntu host, and consider a GHCR-published image so these hosts skip the build toolchain.
