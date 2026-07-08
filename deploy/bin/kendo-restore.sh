#!/usr/bin/env bash
# Restore a kendo Postgres dump produced by kendo-backup.sh.
#
#   Usage: kendo-restore.sh /path/to/kendo-YYYYmmdd-HHMMSS.dump
#
# DESTRUCTIVE: drops and recreates the `kendo` database. Stop the app first so
# nothing writes mid-restore:
#     systemctl --user stop kendo-app
#     ./kendo-restore.sh <dump>
#     systemctl --user start kendo-app
set -euo pipefail

dump="${1:?usage: kendo-restore.sh <dump-file>}"
[[ -f "$dump" ]] || { echo "no such file: $dump" >&2; exit 1; }

read -rp "This will DROP and recreate the 'kendo' database. Type 'yes' to proceed: " ok
[[ "$ok" == "yes" ]] || { echo "aborted"; exit 1; }

# Recreate the database (terminate other connections first).
podman exec -i kendo-db psql -U kendo -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE datname = 'kendo' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS kendo;
CREATE DATABASE kendo OWNER kendo;
SQL

# Restore the custom-format dump.
podman exec -i kendo-db pg_restore -U kendo -d kendo --no-owner <"$dump"

echo "restore complete from: $dump"
