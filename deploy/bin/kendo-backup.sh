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
#     KENDO_BACKUP_REMOTE_TIMEOUT=1h             cut rclone off after this
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
# sourced: the file holds settings, never code. It looks like an env file, so
# it is written like one: a CRLF ending, surrounding spaces, one pair of
# quotes, and a ` # comment` outside them are not part of the value. setup.sh
# reads the file through `--setting NAME` below, so there is one reading of it.
setting() {
  local value="${!1:-}" quoted="^([\"'])(.*)\\1"
  if [[ -z "$value" && -f "$CONFIG" ]]; then
    value=$(sed -n "s/^$1=//p" "$CONFIG" | tail -1)
    value=${value%$'\r'}
    value=${value#"${value%%[![:space:]]*}"}
    if [[ "$value" =~ $quoted ]]; then
      value=${BASH_REMATCH[2]}
    else
      value=$(sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//' <<<"$value")
    fi
  fi
  printf '%s' "$value"
}
if [[ "${1:-}" == --setting ]]; then
  setting "${2:?usage: kendo-backup.sh --setting NAME}"
  exit 0
fi
RECIPIENT=$(setting KENDO_BACKUP_RECIPIENT)
REMOTE=$(setting KENDO_BACKUP_REMOTE)
KEEP_DAYS=$(setting KENDO_BACKUP_REMOTE_KEEP_DAYS)
TIMEOUT=$(setting KENDO_BACKUP_REMOTE_TIMEOUT)
TIMEOUT=${TIMEOUT:-1h}

# offsite_problem — why this run's backups would not reach the remote, or
# nothing when they would. The nightly run acts on it and `setup.sh check` asks
# for it through --check-offsite, so the two can never disagree.
offsite_problem() {
  # An rclone remote is name:path: a configured name, which may carry
  # options (b2,hard_delete=true:bucket), or a connection string
  # (:s3,provider=…:bucket). Anything else rclone takes as a local path, and
  # the expiry below would then delete this host's own backups — so a name
  # rclone would not accept, a leading -, the :local backend, and any `/`
  # in the options (a wrapper such as :alias,remote=/home/… pointing at local
  # disk) are refused. A configured remote of type local is rclone's config,
  # beyond what this can see.
  local remote_form='^(:[[:alnum:]]+|[[:alnum:]_.+@][[:alnum:]_.+@ -]*)(,[^:/]*)?:'
  if [[ -z "$REMOTE" ]]; then
    echo "No off-site copy configured — backups do not survive losing this host (docs/install/backups.md)."
  elif [[ -z "$RECIPIENT" ]]; then
    echo "Off-site copy to $REMOTE is skipped: backups are not encrypted, and plaintext never leaves this host. Set a backup key with \`setup.sh backup-key\`."
  elif [[ "$REMOTE" =~ ^:local[,:] || ! "$REMOTE" =~ $remote_form ]]; then
    echo "KENDO_BACKUP_REMOTE must be an rclone remote and path, like gdrive:kendo-backups — not '$REMOTE'."
  elif ! command -v rclone >/dev/null; then
    echo "KENDO_BACKUP_REMOTE is set, but rclone is not installed — nothing is copied off-site (sudo dnf install -y rclone   # or: sudo apt install -y rclone)."
  # It reaches --min-age, so only a plain number: 0 would expire this run's own
  # copies, and anything else is a typo that must not widen a deletion.
  elif ! [[ -z "$KEEP_DAYS" || "$KEEP_DAYS" =~ ^[1-9][0-9]*$ ]]; then
    echo "KENDO_BACKUP_REMOTE_KEEP_DAYS must be a whole number of days, 1 or more — not '$KEEP_DAYS'."
  # It reaches `timeout`, which reads anything else as the command to run.
  elif ! [[ "$TIMEOUT" =~ ^[1-9][0-9]*[smhd]?$ ]]; then
    echo "KENDO_BACKUP_REMOTE_TIMEOUT must be a duration like 30m or 2h — not '$TIMEOUT'."
  fi
}
if [[ "${1:-}" == --check-offsite ]]; then
  problem=$(offsite_problem)
  [[ -n "$problem" ]] || { echo "Off-site copy configured: $REMOTE"; exit 0; }
  echo "$problem"
  exit 1
fi

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

# A backup on this host does not survive losing it. No remote, or no key to
# encrypt with, is a choice, not a failure; anything else is the remote's
# problem, reported as one.
offsite_failed() {
  echo "Off-site copy to $REMOTE failed: $1 The local backup is complete and kept." >&2
  exit 75
}
# remote WHAT ARGS... — rclone, cut off after TIMEOUT. The unit is a oneshot
# with no start timeout of its own, so a stalled upload would otherwise hold
# it "activating": no backup the next night, and `setup.sh upgrade` waiting.
remote() {
  local what=$1 status=0
  shift
  timeout --kill-after=1m "$TIMEOUT" rclone "$@" || status=$?
  case $status in
    0) ;;
    124|137) offsite_failed "rclone did not finish within $TIMEOUT ($what); raise KENDO_BACKUP_REMOTE_TIMEOUT if the link is slow." ;;
    *) offsite_failed "rclone could not $what; check the remote with: rclone lsf $REMOTE." ;;
  esac
}
problem=$(offsite_problem)
if [[ -z "$REMOTE" ]]; then
  echo "$problem"
  exit 0
elif [[ -z "$RECIPIENT" ]]; then
  echo "$problem" >&2
  exit 0
elif [[ -n "$problem" ]]; then
  offsite_failed "$problem"
fi

# Every recent encrypted artefact, not just this run's: rclone skips what the
# remote already has, so a copy that failed on an earlier run catches up here.
# The filter is what keeps plaintext from before the key on this host. The
# window stops at KEEP_DAYS, or a copy expired below would be uploaded again
# the next night; and at the last change to backup.env, which a new key
# rewrites, so copies under a leaked key that were deleted off-site are never
# sent back. A provider lifecycle rule shorter than the window re-sends too:
# set KEEP_DAYS to match it.
# ponytail: a fixed 7-day catch-up; an outage longer than that leaves a gap.
window=$((7 * 86400))
[[ -n "$KEEP_DAYS" ]] && ((KEEP_DAYS * 86400 < window)) && window=$((KEEP_DAYS * 86400))
if [[ -f "$CONFIG" ]]; then
  since_config=$(($(date +%s) - $(stat -c %Y "$CONFIG")))
  ((since_config < window)) && window=$since_config
fi
remote "copy to it" copy "$BACKUP_DIR" "$REMOTE" --max-depth 1 --include 'kendo-*.age' --max-age "${window}s"
echo "copied to $REMOTE"
# `rclone copy` never deletes, so copies expire here, or by the provider's
# lifecycle rule when the credentials cannot delete (leave KEEP_DAYS unset).
# Only our own encrypted artefacts, and nothing below the remote's top level:
# it may be a folder shared with other things.
if [[ -n "$KEEP_DAYS" ]]; then
  remote "expire copies older than $KEEP_DAYS days" \
    delete "$REMOTE" --min-age "${KEEP_DAYS}d" --max-depth 1 --include 'kendo-*.age'
fi
