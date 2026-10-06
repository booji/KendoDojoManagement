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
#
# Encryption (#500): with a backup key configured, each artefact is encrypted
# with `age` to the key's PUBLIC half and gains a .age suffix. The private half
# is never on this host, so nothing here can read a backup back — not even an
# attacker holding the host. `setup.sh backup-key` makes the key and writes
#     KENDO_BACKUP_RECIPIENT=age1...
# to KENDO_BACKUP_CONFIG (default: ~/.config/kendo/backup.env). A value already
# in the environment wins over the file.
set -euo pipefail

BACKUP_DIR="${KENDO_BACKUP_DIR:-$HOME/backups}"
KEEP="${KENDO_BACKUP_KEEP:-14}"
DB="${KENDO_DB_CONTAINER:-kendo-db}"
UPLOADS_VOLUME="${KENDO_UPLOADS_VOLUME:-kendo-app-uploads}"
CONFIG="${KENDO_BACKUP_CONFIG:-$HOME/.config/kendo/backup.env}"
# Read, not sourced: the file holds settings, never code.
if [[ -z "${KENDO_BACKUP_RECIPIENT:-}" && -f "$CONFIG" ]]; then
  KENDO_BACKUP_RECIPIENT=$(sed -n 's/^KENDO_BACKUP_RECIPIENT=//p' "$CONFIG" | tail -1)
fi
RECIPIENT="${KENDO_BACKUP_RECIPIENT:-}"
# No key still backs up: no backup is worse than a plaintext one, and failing
# would break the nightly timer of every install from before #500. A key with
# no `age` to use it fails, though — that operator asked for encryption.
if [[ -z "$RECIPIENT" ]]; then
  echo "WARNING: backups are not encrypted — set a backup key with \`setup.sh backup-key\` (docs/install/backups.md)." >&2
elif ! command -v age >/dev/null; then
  echo "A backup key is configured but \`age\` is not installed — nothing was written. Install it: sudo dnf install -y age   # or: sudo apt install -y age" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
# Clear any .partial left by a previous run that died mid-write (see
# write_artefact). Nothing else in this directory uses that suffix.
rm -f -- "$BACKUP_DIR"/*.partial
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/kendo-${stamp}.dump"

# Write to .partial and rename only on success. A shell redirect creates the
# target before the command runs, so without this a failure would leave a
# truncated file that prune counts — and restore trusts — as a real backup.
# With a key, encryption happens in the pipe: plaintext never touches disk.
write_artefact() {
  local dest="$1"
  shift
  if [[ -n "$RECIPIENT" ]]; then
    dest+=".age"
    "$@" | age -r "$RECIPIENT" >"$dest.partial"
  else
    "$@" >"$dest.partial"
  fi
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
# Each glob takes the plaintext and the .age form together, so backups from
# before a key was set age out like any other.
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
prune 'kendo-*.dump*' "dump(s)"
prune 'kendo-uploads-*.tar*' "uploads archive(s)"

# REMINDER: copy $BACKUP_DIR off-box (rsync/restic/object storage). A backup on
# the same host does not survive host loss. (Out of scope to implement here.)
