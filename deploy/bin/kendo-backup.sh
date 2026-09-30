#!/usr/bin/env bash
# Nightly backup for the kendo stack. Runs as the rootless `kendo` user via the
# kendo-backup.timer systemd user unit. Writes two artefacts per run, sharing a
# timestamp so a dump and its uploads tarball can be paired on restore:
#   kendo-<stamp>.dump          Postgres, custom format
#   kendo-uploads-<stamp>.tar   the kendo-app-uploads volume (logos/backgrounds)
# Both are pruned to the newest N.
#
#   Install: ~kendo/.local/bin/kendo-backup.sh  (chmod +x)
#   Tune via env in the .service unit:
#     KENDO_BACKUP_DIR  (default: $HOME/backups)
#     KENDO_BACKUP_KEEP (default: 14)
#   The container and volume names default to the Quadlet ones; the Compose
#   stack's are project-scoped, and `setup.sh upgrade` passes those:
#     KENDO_DB_CONTAINER   (default: kendo-db)
#     KENDO_UPLOADS_VOLUME (default: kendo-app-uploads)
set -euo pipefail

BACKUP_DIR="${KENDO_BACKUP_DIR:-$HOME/backups}"
KEEP="${KENDO_BACKUP_KEEP:-14}"
DB="${KENDO_DB_CONTAINER:-kendo-db}"
UPLOADS_VOLUME="${KENDO_UPLOADS_VOLUME:-kendo-app-uploads}"

mkdir -p "$BACKUP_DIR"
# Clear any .partial left by a previous run that died mid-write (see
# write_artefact). Nothing else in this directory uses that suffix.
rm -f -- "$BACKUP_DIR"/*.partial
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/kendo-${stamp}.dump"

# Write to .partial and rename only on success. A shell redirect creates the
# target before the command runs, so without this a failure would leave a
# truncated file that prune counts — and restore trusts — as a real backup.
write_artefact() {
  local dest="$1"
  shift
  "$@" >"$dest.partial"
  mv -- "$dest.partial" "$dest"
  echo "written: $dest ($(du -h "$dest" | cut -f1))"
}

# -Fc = custom format (compressed, restorable with pg_restore). Password is read
# from POSTGRES_PASSWORD_FILE inside the container, so no secret on the CLI.
write_artefact "$out" podman exec "$DB" pg_dump -U kendo -d kendo -Fc

# Uploaded logos and login backgrounds live only in this volume — they are not
# in the database, so the pg_dump above does not cover them.
uploads="$BACKUP_DIR/kendo-uploads-${stamp}.tar"
write_artefact "$uploads" podman volume export "$UPLOADS_VOLUME"

# Prune each artefact type independently: keep the newest $KEEP, delete the rest.
# The .dump glob does not match kendo-uploads-*.tar, so the two do not interfere.
# $1 is a glob relative to $BACKUP_DIR, expanded here so a directory containing
# spaces still works.
prune() {
  local label="$2"
  mapfile -t old < <(ls -1td "$BACKUP_DIR"/$1 2>/dev/null | tail -n +$((KEEP + 1)))
  if ((${#old[@]})); then
    rm -f -- "${old[@]}"
    echo "pruned ${#old[@]} old $label"
  fi
}
prune 'kendo-*.dump' "dump(s)"
prune 'kendo-uploads-*.tar' "uploads archive(s)"

# REMINDER: copy $BACKUP_DIR off-box (rsync/restic/object storage). A backup on
# the same host does not survive host loss. (Out of scope to implement here.)
