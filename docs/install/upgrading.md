# Upgrading

An upgrade is three steps: back up, pull the image you pin, restart onto it.
Nothing in it touches a deployment file. Once installed, the compose file,
the units, the timers, the scripts, the env files and the Traefik config are
yours, edits included, and no upgrade step overwrites one (#604).

A release that changes one of those files says so in its release notes,
under **Operator action**. Read the notes before you upgrade, and apply each
action first, as [Operator actions](#operator-actions) describes.

## Quick self-host (Compose)

```bash
./setup.sh upgrade
```

An upgrade runs `alembic upgrade head` against your live database, so this
takes a backup first: `deploy/bin/kendo-backup.sh` writes the database dump and
the uploads tarball to `~/backups` and says where. Then it pulls the image
`KENDO_IMAGE` in `.env` names and recreates the stack on it. It changes none of
your files.

After it, `podman-compose logs migrate` names the schema revision the database
started at and the one it is at now, with each revision applied in between
(#606).

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

`./setup.sh upgrade` is the Compose path only. On a Quadlet host, run these
steps as `kendo`:

```bash
# Back up first: kendo-migrate runs `alembic upgrade head` against your live
# database. This is the backup to restore if the upgrade fails — see
# Backups § Restore.
systemctl --user start kendo-backup.service

# Pull the image your units pin. Restarting a unit never fetches a newer
# image under the same tag, so without this nothing changes.
podman pull "$(sed -n 's/^Image=//p' ~/.config/containers/systemd/kendo-app.container)"

# Restart onto it: kendo-migrate migrates, then the app starts.
systemctl --user restart kendo-migrate kendo-app
```

Then, from your admin account, read what `kendo-migrate` did: the revision the
schema started at, each one applied, and the one it is at now (#606). On a
failure it says why. `kendo` cannot read the journal itself
([Deployment § Logs](../deployment.md#9-logs)):

```bash
sudo journalctl _UID=$(id -u kendo) _SYSTEMD_USER_UNIT=kendo-migrate.service --since "1 hour ago" --no-pager
```

If it failed, restore the backup taken above — [Backups § Restore](backups.md#restore).

Traefik and PostgreSQL run images their own units pin. A release that moves
one of those pins says so as an Operator action. Once you have edited the
unit, pull the new image and add `kendo-traefik` or `kendo-db` to the restart.

## Operator actions

Each release's notes list every change to a deployment file under **Operator
action**, with a Compose heading and a Quadlet heading as each applies. Each
says what to change, and what happens if you do not. A new setting that has a
safe default needs no action. Apply them before the routine upgrade above, so
that its restart picks them up.

To see the release's version of a file, extract the release's bundle into a
directory of its own. Never extract it over your install: the bundle's files
would replace yours. Set `IMAGE` to the image you are upgrading to — what
`Image=` in `kendo-app.container` names on Quadlet, or `KENDO_IMAGE` in `.env`
on Compose:

```bash
podman pull "$IMAGE"
mkdir -p ~/kendo-release
podman run --rm "$IMAGE" init | tar -x -C ~/kendo-release
```

Compare the file the action names with your copy, and carry the change into
yours, keeping your own edits — the firewalld ports of [Deployment §
1.2](../deployment.md#12-allow-rootless-binding-of-ports-80443) in
`kendo-traefik.container`, say:

| Bundle file | Your copy on Compose | Your copy on Quadlet | Then |
|---|---|---|---|
| `deploy/quadlet/*` | — | `~/.config/containers/systemd/` | `systemctl --user daemon-reload`, then restart the unit |
| `deploy/systemd/*` | — | `~/.config/systemd/user/` | `systemctl --user daemon-reload`; `enable --now` a new timer |
| `deploy/bin/*` | `deploy/bin/` | `~/.local/bin/` (`install -m 755`) | nothing: the next backup runs it |
| `docker-compose.yml` | `docker-compose.yml` | — | the routine upgrade recreates the stack |
| `setup.sh` | `setup.sh` | `~/src/setup.sh` | nothing: take it whole, it holds no setting of yours |
| `.env.example` | `.env` | — | the routine upgrade |
| `deploy/env/kendo-app.env.example` | `kendo-app.env` | `~/kendo/kendo-app.env` | the routine upgrade |
| `deploy/traefik/selfhost/` | `deploy/traefik/selfhost/` | — | Traefik reloads `dynamic/` by itself; restart the proxy for `traefik.yml` |
| `deploy/traefik/` | — | `~/kendo/traefik/` | Traefik reloads `dynamic/` by itself; restart `kendo-traefik` for `traefik.yml` |

A changed unit needs the `daemon-reload` before its restart: Quadlet generates
the service from the file only then. An env file needs only the restart.

### A new setting in the env file

When a release adds a setting without a safe default, its Operator action
names it. The app does not see a key that is absent from your env file: the
unit and the compose file pass that one file and nothing else. To find every
key the release's example has that yours lacks, compare **keys**, not lines.
Values legitimately differ per host, so a plain `diff` is all noise. On
Quadlet:

```bash
diff <(grep -oE '^[A-Z0-9_]+=' ~/kendo/kendo-app.env | tr -d = | sort) \
     <(grep -oE '^[A-Z0-9_]+=' ~/kendo-release/deploy/env/kendo-app.env.example | tr -d = | sort)
```

On Compose, compare `kendo-app.env` in the install directory instead. Empty
output means nothing new. A `>` line is a setting you lack: copy it across
with its comment. Then, once the routine upgrade has restarted the app, check
that the app received it. A restart proves the unit started, not that the
value arrived:

```bash
podman exec kendo-app printenv APP_ENV JWT_EXPIRE_MINUTES   # Quadlet
podman-compose exec app printenv APP_ENV JWT_EXPIRE_MINUTES # Compose
# APP_ENV=production
# JWT_EXPIRE_MINUTES=480
```

## Pinning a Version, and rolling back

The units pin the Release line's moving tag, `:0.1`, so the routine upgrade
takes each patch release. To run an exact Version instead, such as a release
candidate or the one you ran before, edit the pin. Then run the routine
upgrade, which pulls what the pin names.

On Quadlet, the pin is `Image=` in `kendo-app.container`,
`kendo-migrate.container` and `kendo-ip-retention.container`. Keep the three
the same:

```bash
TAG=0.1.0-rc3   # the tag to run
cd ~/.config/containers/systemd
sed -i "s|^Image=.*|Image=ghcr.io/booji/kendodojomanagement:$TAG|" \
  kendo-app.container kendo-migrate.container kendo-ip-retention.container
systemctl --user daemon-reload
```

On Compose, the pin is `KENDO_IMAGE` in `.env`: the image name, a colon and
the tag.

Rolling back is the same edit, back to the tag you ran before. A migration
has to be undone too, so restore the backup the upgrade took, after the edit:
[Backups § Restore](backups.md#restore) ends by restarting `kendo-migrate`, on
the image the pin now names. A failed `./setup.sh upgrade` prints these steps
for you, with the digest of the image that was running.

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

## Upgrading to a new Release line

Within a Release line (`:0.1`) every upgrade is the routine one above, plus
any Operator actions its notes list. The exception is a security fix that
cannot avoid breaking: its release notes say so under a Security heading, and
the upgrade stops until you have acted. Moving to the next (`:0.2`) is a
**Breaking change**: it needs a step only you can take, or carries a migration
that returning to the previous image cannot undo. Each one gets its own
section here, headed "Upgrading to 0.Y", with the operator action its release
notes list. Read it before you change the pin.

None yet: 0.1 is the first Release line.

## From a release candidate: splitting `.env` once

Quick self-host only, and only for a host set up with `v0.1.0-rc1` or
`v0.1.0-rc2`. Those kept every app setting in `.env`. From `v0.1.0-rc3` the
app reads its settings from `kendo-app.env` next to `docker-compose.yml`
instead, written from `deploy/env/kendo-app.env.example`, the file the
hardened deployment uses too (#603). `.env` keeps only the image pin, the db
settings and the secrets. `./setup.sh upgrade` stops, before it backs up or
changes anything, while `kendo-app.env` is missing.

`.env` pins the rc it was set up with, so first point `KENDO_IMAGE` at the
release ([Pinning a Version](#pinning-a-version-and-rolling-back)). Extract
that release's bundle, as [Operator actions](#operator-actions) describes.
Then, in the directory that holds `.env`, take its `setup.sh`, compose file
and env example, and create `kendo-app.env` once:

```bash
cp ~/kendo-release/setup.sh setup.sh
cp ~/kendo-release/docker-compose.yml docker-compose.yml
mkdir -p deploy/env
cp ~/kendo-release/deploy/env/kendo-app.env.example deploy/env/
cp deploy/env/kendo-app.env.example kendo-app.env
```

The rc's own `setup.sh upgrade` would refresh the bundle itself and recreate
the stack without `kendo-app.env`; the new one does neither.

If you had edited `docker-compose.yml` (a BYO certificate's mount, say), make
the same edit again in the new one.

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

## From `v0.1.0-rc1` on Quadlet: installing the backup units once

A Quadlet host set up with `v0.1.0-rc1` has no backup units: `setup.sh
--quadlet` installs them from `v0.1.0-rc2` (#576). Without them the routine
upgrade's first step fails. Install them once, as `kendo`, from the release's
bundle extracted as [Operator actions](#operator-actions) describes:

```bash
cd ~/kendo-release
install -m 755 deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh ~/.local/bin/
cp deploy/systemd/kendo-backup.service deploy/systemd/kendo-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kendo-backup.timer
```
