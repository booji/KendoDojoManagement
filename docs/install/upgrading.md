# Upgrading

## Quick self-host (Compose)

```bash
./setup.sh upgrade
```

An upgrade runs `alembic upgrade head` against your live database, so this
takes a backup first: `deploy/bin/kendo-backup.sh` writes the database dump and
the uploads tarball to `~/backups` and says where. Then it pulls, refreshes the
deployment bundle from the image it just pulled, and recreates the stack. The
bundle holds the compose file, the `.example` config and the Quadlet units, so
they always match the app they run. Any of those files that changed is listed,
and your previous copy is kept as `.bak`. `.env` and your filled-in Traefik
files are never touched.

A file you edited yourself (a BYO certificate's mount in `docker-compose.yml`,
say) is never overwritten. If this release also changed it, the new version is
written next to it as `.new` and the upgrade stops before anything is
recreated. Merge the two, re-run `./setup.sh upgrade`, and it carries on.

If the upgrade or the migration fails, it prints the exact
`kendo-restore.sh` command for the backup it just took. It also prints the
digest of the image that was running, to pin back to. Restoring the data alone
is only half a rollback, because the new image would migrate it straight back
up.

A plain `podman-compose pull && podman-compose up -d` is not enough on Podman:
podman-compose recreates a container only when the compose file changes, so a
new image under the same `:1` tag never starts.

> **Upgrading a Compose stack first started before #385:** the image now runs as
> the unprivileged user `kendo` (uid 1001), but Podman only takes a volume's
> ownership from the image when the volume is *empty*, so a `static_uploads`
> created by the old root-running image stays root-owned and the first upload
> after the upgrade fails with a permission error. Chown it once:
>
> ```bash
> # Compose prefixes the volume with the project name — find it first:
> vol=$(podman volume ls --format '{{.Name}}' | grep static_uploads)
> podman unshare chown -R 1001:1001 \
>   "$(podman volume inspect "$vol" --format '{{.Mountpoint}}')"
> ```
>
> The Quadlet path needs no such step — `kendo-app.container` mounts the volume
> with `:U`, which chowns it on every start. Fresh stacks need nothing either.

## Hardened deployment (Quadlet)

**When a Quadlet unit, the Traefik config or the env file changes upstream**,
the Upgrade command above is not enough — it pulls the image but reuses the
units already in `~/.config/containers/systemd/`, the Traefik config already in
`~/kendo/traefik/`, and it never touches `~/kendo/kendo-app.env`. Each is a
copy made once at install time; pulling a new image updates neither.

```bash
# Re-extract the bundle from the tag you are pinned to — it ships inside the
# image, so the units below match the app they start.
cd ~/src && podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x

# Units: re-run the copy from Hardened deployment §2-4, then daemon-reload so Quadlet regenerates.
cp deploy/quadlet/kendo-*.network   ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.volume    ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.container ~/.config/containers/systemd/
systemctl --user daemon-reload

# Traefik dynamic config — keep your Host() rule, take the rest. Traefik
# watches this directory, so no restart is needed once the file lands.
diff deploy/traefik/dynamic/kendo.yml ~/kendo/traefik/dynamic/kendo.yml

systemctl --user restart kendo-migrate kendo-app
```

The env file is per-host and needs comparing rather than copying — see
[Refreshing the env file](#refreshing-the-env-file-after-an-upgrade).

**A host installed before #412 that uses DNS-01 needs the drop-in before its
next unit refresh.** `kendo-traefik.container` used to hardcode
`CF_DNS_API_TOKEN_FILE` and the `kendo_cf_dns_token` secret; it no longer
does, so re-copying it leaves Traefik with no DNS credentials and ACME
renewal fails. Write the drop-in from [§5](../deployment.md#5-tls-options) first — pointing
`Secret=` at your existing `kendo_cf_dns_token` is fine, no new secret needed.

**Hosts installed before #385 need the unit refresh now.** That change made
the app run unprivileged and mounts the uploads volume `:U`; both live in
`kendo-app.container`, so neither reaches an existing host until the copy
above. The edge health check lives in the Traefik dynamic config.

## Refreshing the env file after an upgrade

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

## Upgrading a deployment created before the Alembic baseline (issue #264)

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
