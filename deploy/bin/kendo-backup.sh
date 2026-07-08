#!/usr/bin/env bash
# Nightly Postgres backup for the kendo stack. Runs as the rootless `kendo` user
# via the kendo-backup.timer systemd user unit. Writes a compressed custom-format
# dump and prunes to the newest N.
#
#   Install: ~kendo/.local/bin/kendo-backup.sh  (chmod +x)
#   Tune via env in the .service unit:
#     KENDO_BACKUP_DIR  (default: $HOME/backups)
#     KENDO_BACKUP_KEEP (default: 14)
set -euo pipefail

BACKUP_DIR="${KENDO_BACKUP_DIR:-$HOME/backups}"
KEEP="${KENDO_BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/kendo-${stamp}.dump"

# -Fc = custom format (compressed, restorable with pg_restore). Password is read
# from POSTGRES_PASSWORD_FILE inside the container, so no secret on the CLI.
podman exec kendo-db pg_dump -U kendo -d kendo -Fc >"$out"

echo "backup written: $out ($(du -h "$out" | cut -f1))"

# Prune: keep the newest $KEEP dumps, delete the rest.
mapfile -t old < <(ls -1t "$BACKUP_DIR"/kendo-*.dump 2>/dev/null | tail -n +$((KEEP + 1)))
if ((${#old[@]})); then
  rm -f -- "${old[@]}"
  echo "pruned ${#old[@]} old backup(s)"
fi

# REMINDER: copy $BACKUP_DIR off-box (rsync/restic/object storage). A backup on
# the same host does not survive host loss. (Out of scope to implement here.)
