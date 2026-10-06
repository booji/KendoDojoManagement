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
#
# Off-site (#502), optional, in the same file:
#     KENDO_BACKUP_REMOTE=gdrive:kendo-backups   an rclone remote and path
#     KENDO_BACKUP_REMOTE_KEEP_DAYS=90           expire copies older than this
# Each run's encrypted artefacts are copied there with rclone (the kendo user's
# own rclone.conf). Plaintext never leaves the host. An off-site failure keeps
# the local backup and exits 75 (EX_TEMPFAIL), which setup.sh carries on past —
# a code nothing in the local half exits with by accident. systemd shows it as
# a failed run like any other, which is the point: someone should look.
set -euo pipefail

BACKUP_DIR="${KENDO_BACKUP_DIR:-$HOME/backups}"
KEEP="${KENDO_BACKUP_KEEP:-14}"
DB="${KENDO_DB_CONTAINER:-kendo-db}"
UPLOADS_VOLUME="${KENDO_UPLOADS_VOLUME:-kendo-app-uploads}"
CONFIG="${KENDO_BACKUP_CONFIG:-$HOME/.config/kendo/backup.env}"
# setting NAME — the environment's value, else the config file's. Read, not
# sourced: the file holds settings, never code.
setting() {
  local value="${!1:-}"
  if [[ -z "$value" && -f "$CONFIG" ]]; then
    value=$(sed -n "s/^$1=//p" "$CONFIG" | tail -1)
  fi
  printf '%s' "$value"
}
RECIPIENT=$(setting KENDO_BACKUP_RECIPIENT)
REMOTE=$(setting KENDO_BACKUP_REMOTE)
KEEP_DAYS=$(setting KENDO_BACKUP_REMOTE_KEEP_DAYS)
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
# Each artefact this run wrote is kept in `written`, for the off-site copy.
written=()
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
  written+=("$dest")
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

# A backup on this host does not survive losing it.
if [[ -z "$REMOTE" ]]; then
  echo "no off-site copy configured"
  exit 0
fi
if [[ -z "$RECIPIENT" ]]; then
  echo "off-site copy skipped: these backups are not encrypted, and plaintext never leaves this host. Set a backup key with \`setup.sh backup-key\`." >&2
  exit 0
fi
offsite_failed() {
  echo "Off-site copy to $REMOTE failed: $1 The local backup is complete and kept." >&2
  exit 75
}
# An rclone remote is name:path. A local path would pass, and `delete` below
# would then expire this host's own backups; a leading - would be a flag.
remote_form='^[[:alnum:]_.+@][[:alnum:]_.+@ -]*:'
[[ "$REMOTE" =~ $remote_form ]] ||
  offsite_failed "KENDO_BACKUP_REMOTE must be an rclone remote and path, like gdrive:kendo-backups — not '$REMOTE'."
command -v rclone >/dev/null ||
  offsite_failed "KENDO_BACKUP_REMOTE is set, but rclone is not installed (sudo dnf install -y rclone   # or: sudo apt install -y rclone)."
# It reaches --min-age, so only a plain number: 0 would expire this run's own
# copies, and anything else is a typo that must not widen a deletion.
[[ -z "$KEEP_DAYS" || "$KEEP_DAYS" =~ ^[1-9][0-9]*$ ]] ||
  offsite_failed "KENDO_BACKUP_REMOTE_KEEP_DAYS must be a whole number of days, 1 or more — not '$KEEP_DAYS'."

# Only this run's artefacts: `rclone copy` of the directory would also carry
# any plaintext backup from before the key was set.
for f in "${written[@]}"; do
  rclone copy "$f" "$REMOTE" ||
    offsite_failed "rclone could not copy $f; check the remote with: rclone lsf $REMOTE."
done
echo "copied to $REMOTE"
# `rclone copy` never deletes, so copies expire here, or by the provider's
# lifecycle rule when the credentials cannot delete (leave KEEP_DAYS unset).
# Only our own encrypted artefacts, and nothing below the remote's top level:
# it may be a folder shared with other things.
if [[ -n "$KEEP_DAYS" ]]; then
  rclone delete "$REMOTE" --min-age "${KEEP_DAYS}d" --max-depth 1 --include 'kendo-*.age' ||
    offsite_failed "rclone could not expire copies older than $KEEP_DAYS days; check the remote with: rclone lsf $REMOTE."
fi
