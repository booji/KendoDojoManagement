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
up. Run every printed step: the last one re-runs `migrate`, which the app
needs after a restore (#481).

If your backups are encrypted, have the backup key to hand before you start:
a rollback restores the backup just taken, and `kendo-restore.sh` asks for the
key. `setup.sh upgrade` reminds you. See [Backups](backups.md#the-backup-key).

Some migrations check your data before changing the schema, and stop if they
find rows only you can decide about — for example an account that belongs to no
member, or a member whose email differs from the account that signs in as them
(#432). They stop before changing anything, name the rows, and say what to fix.
Fix those rows, then run `./setup.sh upgrade` again.

A plain `podman-compose pull && podman-compose up -d` is not enough on Podman:
podman-compose recreates a container only when the compose file changes, so a
new image under the same `:0.1` tag never starts.

## Hardened deployment (Quadlet)

`./setup.sh upgrade` is the Compose path only; on a Quadlet host, run these
steps as `kendo`. Restarting a unit never fetches a newer image under the same
tag, and the units in `~/.config/containers/systemd/`, the Traefik config in
`~/kendo/traefik/` and `~/kendo/kendo-app.env` are copies made at install
time, so the upgrade pulls first and then refreshes each copy.

```bash
# Back up first: kendo-migrate runs `alembic upgrade head` against your live
# database. This is the backup to restore if the upgrade fails — see
# Backups § Restore. A host set up before setup.sh installed the backup units
# has none, so copy them from the bundle already in ~/src first.
cd ~/src
cp deploy/systemd/kendo-backup.service deploy/systemd/kendo-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user start kendo-backup.service

# Pull every image the units run. Without this the steps below reuse the
# cached images and nothing changes.
podman pull ghcr.io/booji/kendodojomanagement:0.1
podman pull docker.io/library/traefik:v3.3
podman pull docker.io/library/postgres:16-alpine

# Re-extract the bundle from the image just pulled — it ships inside the
# image, so the units below match the app they start.
podman run --rm ghcr.io/booji/kendodojomanagement:0.1 init | tar -x

# Units: re-run the copy from Hardened deployment §2-4, then daemon-reload so Quadlet regenerates.
cp deploy/quadlet/kendo-*.network   ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.volume    ~/.config/containers/systemd/
cp deploy/quadlet/kendo-*.container ~/.config/containers/systemd/
cp deploy/systemd/kendo-ip-retention.timer deploy/systemd/kendo-backup.service \
   deploy/systemd/kendo-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
# Idempotent: enables each timer that is not enabled already.
systemctl --user enable --now kendo-ip-retention.timer kendo-backup.timer

# Backup scripts: the timer runs the copies in ~/.local/bin, not the bundle's.
install -m 755 deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh ~/.local/bin/

# Traefik dynamic config — keep your Host() rule, take the rest. Traefik
# watches this directory, so no restart is needed once the file lands.
diff deploy/traefik/dynamic/kendo.yml ~/kendo/traefik/dynamic/kendo.yml

# Restart onto the pulled images: kendo-migrate migrates, then the app starts.
systemctl --user restart kendo-db kendo-migrate kendo-app kendo-traefik
```

If `kendo-migrate` fails (`systemctl --user status kendo-migrate`), restore the
backup taken above — [Backups § Restore](backups.md#restore).

The env file is per-host and needs comparing rather than copying — see
[Refreshing the env file](#refreshing-the-env-file-after-an-upgrade).

## Checking an image came from this repository

Each release image is signed by the release workflow with
[cosign](https://docs.sigstore.dev/cosign/) keyless signing (#457). To check
the image you are about to run, with cosign installed:

```bash
cosign verify ghcr.io/booji/kendodojomanagement:0.1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/booji/KendoDojoManagement/\.github/workflows/release\.yml@refs/tags/v'
```

It fails unless the image's digest was signed by that workflow on a release
tag. Podman does not check this by itself yet (#518). The signature is recorded in Sigstore's public transparency log,
which names this repository, the workflow and the release tag.

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
re-copying and a `daemon-reload` first — [Hardened deployment
(Quadlet)](#hardened-deployment-quadlet) above has that sequence.

Then verify the app actually received it — a restart proves the unit started,
not that the value arrived:

```bash
podman exec kendo-app printenv APP_ENV JWT_EXPIRE_MINUTES
# APP_ENV=production
# JWT_EXPIRE_MINUTES=480
```

## Upgrading to a new Release line

Within a Release line (`:0.1`) every upgrade is the routine one above. The
exception is a security fix that cannot avoid breaking: its release notes say
so under a Security heading, and the upgrade stops until you have acted. Moving
to the next (`:0.2`) is a **Breaking change**: it needs a step only you can
take, or carries a migration that returning to the previous image cannot undo.
Each one gets its own section here, headed "Upgrading to 0.Y", with the
operator action its release notes list. Read it before you change the pin.

None yet: 0.1 is the first Release line.

## From a release candidate: splitting `.env` once

Quick self-host only, and only for a host set up with `v0.1.0-rc1` or
`v0.1.0-rc2`. Those kept every app setting in `.env`. From `v0.1.0-rc3` the
app reads its settings from `kendo-app.env` next to `docker-compose.yml`
instead, written from `deploy/env/kendo-app.env.example`, the file the
hardened deployment uses too (#603). `.env` keeps only the image pin, the db
settings and the secrets. `./setup.sh upgrade` stops, before it backs up or
changes anything, while `kendo-app.env` is missing.

Create it once, in the directory that holds `.env`:

```bash
cp deploy/env/kendo-app.env.example kendo-app.env
```

Then copy your own values from `.env` into `kendo-app.env`, key for key:
`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `CORS_ORIGINS` and `TZ` always, and any
other app setting you changed from its default (`JWT_EXPIRE_MINUTES`,
`SESSION_MAX_MINUTES`, the `*_MIN_DURATION_MS` floors and so on). A wrong
`WEBAUTHN_*` value here makes every passkey ceremony fail, so check those
three against your domain. Leave the secrets in `.env`: `DATABASE_URL`,
`MIGRATION_DATABASE_URL`, `JWT_SECRET`, `SETUP_TOKEN` and `POSTGRES_*` never
go in `kendo-app.env`, because the app reads that file whole and must never
see the superuser login (ADR-0007).

The app settings left in `.env` are ignored from now on. Delete them, so that
nobody tunes a value there that never reaches the app. Keep `KENDO_IMAGE`,
`TZ` (the db's), `POSTGRES_*`, `MIGRATION_DATABASE_URL`, `DATABASE_URL`,
`JWT_SECRET` and `SETUP_TOKEN`. Then upgrade as usual:

```bash
./setup.sh upgrade
./setup.sh check
```
