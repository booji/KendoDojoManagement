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
# Encrypted backups (.dump.age / .tar.age) are restored the same way: it asks
# for the backup key — the AGE-SECRET-KEY-1... line saved when the key was set
# — and checks it before anything is changed. Paste it at the prompt; it is
# not echoed and is never written to disk.
#
# DESTRUCTIVE: drops and recreates the `kendo` database. Stop the app first so
# nothing writes mid-restore (`systemctl --user stop kendo-app`, or on Compose
# `podman-compose stop app`); it prints what to run after.
#
# Privileges are not restored (--no-privileges, #481): the dump's GRANTs to
# kendo_app fail on a fresh server where migrate has not yet created that role.
# Nor are they needed: the DROP/CREATE below resets the database's own grants
# too (CONNECT for kendo_app, TEMPORARY revoked from PUBLIC), and migrate
# re-applies every one. Until it has run, kendo_app can read no table.
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

# Encrypted backups (#500): the private half of the backup key is pasted here —
# it is never kept on this host — and passes only through pipes, as does what
# it decrypts. Each encrypted input is decrypted in full to /dev/null first, so
# a wrong key or a truncated file stops the restore before the DROP below
# rather than after it.
key=""

# The contents of an artefact, decrypted on the way out when it is a .age.
open_artefact() {
  if [[ "$1" == *.age ]]; then
    age -d -i <(printf '%s\n' "$key") "$1"
  else
    cat -- "$1"
  fi
}

if [[ "$dump" == *.age || "$uploads" == *.age ]]; then
  command -v age >/dev/null ||
    { echo "This backup is encrypted, and \`age\` is not installed: sudo dnf install -y age   # or: sudo apt install -y age" >&2; exit 1; }
  read -rsp "Backup is encrypted. Paste your backup key (AGE-SECRET-KEY-1...): " key
  echo
  for f in "$dump" "$uploads"; do
    [[ "$f" == *.age ]] || continue
    if ! err=$(open_artefact "$f" 2>&1 >/dev/null); then
      case $err in
        *"no identity matched"*)
          echo "This backup was encrypted with a different key. If keys were rotated, use the key that was active on the date in the filename." >&2 ;;
        *"malformed secret key"*|*"no secret keys"*|*"unknown identity type"*)
          echo "That is not a valid backup key: paste the whole AGE-SECRET-KEY-1... line, exactly as saved. Nothing was changed." >&2 ;;
        *) echo "Could not decrypt $f — nothing was changed: $err" >&2 ;;
      esac
      exit 1
    fi
  done
fi

read -rp "This will DROP and recreate the 'kendo' database. Type 'yes' to proceed: " ok
[[ "$ok" == "yes" ]] || { echo "aborted"; exit 1; }

# Recreate the database (terminate other connections first).
podman exec -i "$DB" psql -U kendo -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE datname = 'kendo' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS kendo;
CREATE DATABASE kendo OWNER kendo;
SQL

# Restore the custom-format dump. Past the DROP, a failure leaves the database
# empty or partial, and the operator has to hear that, not just an exit code.
if ! open_artefact "$dump" | podman exec -i "$DB" pg_restore -U kendo -d kendo --no-owner --no-privileges; then
  echo "Restore failed after the database was dropped: it is now empty or partial. Fix the error above and re-run this restore from $dump." >&2
  exit 1
fi

echo "restore complete from: $dump"

# Uploads are files on a volume, not rows — restored separately. `volume import`
# unpacks over the existing contents; it does not empty the volume first, so any
# file added since the backup survives.
if [[ -n "$uploads" ]]; then
  open_artefact "$uploads" | podman volume import "$UPLOADS_VOLUME" -
  echo "uploads restored from: $uploads"
fi

echo "Next: the app's database user has no grants until migrate re-runs:"
echo "  systemctl --user restart kendo-migrate kendo-app"
echo "  systemctl --user start kendo-traefik   # stopped with kendo-app (#628)"
echo "  (Compose: podman-compose up -d --force-recreate)"
