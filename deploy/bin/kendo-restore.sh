#!/usr/bin/env bash
# Restore a kendo backup produced by kendo-backup.sh.
#
#   Usage: kendo-restore.sh /path/to/kendo-YYYYmmdd-HHMMSS.dump [uploads.tar]
#
# The optional second argument is the matching kendo-uploads-<stamp>.tar, which
# restores uploaded logos and login backgrounds into the kendo-app-uploads
# volume. Pass the tarball sharing the dump's timestamp; omit it to restore the
# database alone.
#
# DESTRUCTIVE: drops and recreates the `kendo` database. Stop the app first so
# nothing writes mid-restore:
#     systemctl --user stop kendo-app
#     ./kendo-restore.sh <dump>
#     systemctl --user start kendo-app
#
# KENDO_DB_CONTAINER / KENDO_UPLOADS_VOLUME name the Compose stack's
# project-scoped container and volume instead of the Quadlet defaults, as in
# kendo-backup.sh.
set -euo pipefail

DB="${KENDO_DB_CONTAINER:-kendo-db}"
UPLOADS_VOLUME="${KENDO_UPLOADS_VOLUME:-kendo-app-uploads}"

dump="${1:?usage: kendo-restore.sh <dump-file> [uploads-tar]}"
uploads="${2:-}"
[[ -f "$dump" ]] || { echo "no such file: $dump" >&2; exit 1; }
[[ -z "$uploads" || -f "$uploads" ]] || { echo "no such file: $uploads" >&2; exit 1; }

# An encrypted backup (#500) is refused here, before the database is dropped:
# fed ciphertext, pg_restore fails only after the DROP. Decrypting in place is
# #501; until then, decrypt by hand with the backup key and pass the result.
for f in "$dump" "$uploads"; do
  if [[ "$f" == *.age ]]; then
    {
      echo "$f is encrypted. Decrypt it with your backup key, then pass the decrypted file:"
      echo "  age -d -i <file holding your backup key> -o ${f%.age} $f"
    } >&2
    exit 1
  fi
done

read -rp "This will DROP and recreate the 'kendo' database. Type 'yes' to proceed: " ok
[[ "$ok" == "yes" ]] || { echo "aborted"; exit 1; }

# Recreate the database (terminate other connections first).
podman exec -i "$DB" psql -U kendo -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE datname = 'kendo' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS kendo;
CREATE DATABASE kendo OWNER kendo;
SQL

# Restore the custom-format dump.
podman exec -i "$DB" pg_restore -U kendo -d kendo --no-owner <"$dump"

echo "restore complete from: $dump"

# Uploads are files on a volume, not rows — restored separately. `volume import`
# unpacks over the existing contents; it does not empty the volume first, so any
# file added since the backup survives.
if [[ -n "$uploads" ]]; then
  podman volume import "$UPLOADS_VOLUME" "$uploads"
  echo "uploads restored from: $uploads"
fi
