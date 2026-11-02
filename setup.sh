#!/usr/bin/env bash
# First-run configuration (#411, #412).
#
#   podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x
#   ./setup.sh              # quick self-host: Compose + .env
#   ./setup.sh --quadlet    # hardened: podman secrets + ~/kendo + Quadlet units
#   ./setup.sh check [--quadlet]   # advisory preflight, any time (#413)
#   ./setup.sh upgrade              # quick self-host: back up, pull, migrate (#414)
#   ./setup.sh backup-key [--quadlet]  # new backup encryption key, e.g. lost or leaked (#500)
#
# Both modes ask the same questions and derive WEBAUTHN_RP_ID /
# WEBAUTHN_ORIGIN / CORS_ORIGINS from one domain answer — an RP_ID typo is the
# whole "passkeys silently don't work" failure class. They differ only in where
# the answers land: .env and deploy/traefik/selfhost/ for Compose, podman
# secrets and ~/kendo/ for Quadlet.
#
# Unprivileged: it never escalates. Host prerequisites are detected and the
# exact `sudo` command printed for the operator to run.
set -euo pipefail

mode=compose
action=setup
case "${1-}${2+ $2}" in
  '') ;;
  --quadlet) mode=quadlet ;;
  check) action=check ;;
  'check --quadlet') action=check mode=quadlet ;;
  upgrade) action=upgrade ;;
  backup-key) action=backup-key ;;
  'backup-key --quadlet') action=backup-key mode=quadlet ;;
  *) echo "Usage: $0 [check|backup-key] [--quadlet]  |  $0 upgrade" >&2; exit 2 ;;
esac

cd "$(dirname "$0")"
selfhost=deploy/traefik/selfhost
hardened=deploy/traefik
kendo=$HOME/kendo
units=$HOME/.config/containers/systemd

if [ "$mode" = quadlet ]; then
  required=(deploy/env/kendo-app.env.example "$hardened/traefik.yml"
            "$hardened/dynamic/kendo.yml" "$hardened/dynamic/byo-cert.yml.example"
            deploy/quadlet/kendo-app.container deploy/quadlet/kendo-edge.network
            deploy/quadlet/kendo-db-data.volume
            deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh)
else
  required=(.env.example "$selfhost/traefik.yml.example" "$selfhost/dynamic/kendo.yml.example"
            deploy/bin/kendo-backup.sh)
fi
# Every action reads backup.env through kendo-backup.sh (backup_setting).
[ "$action" = setup ] || required=(deploy/bin/kendo-backup.sh)
for f in "${required[@]}"; do
  [ -f "$f" ] || { echo "Missing $f — run this from the deployment bundle or a checkout." >&2; exit 1; }
done

ask() { # ask VAR PROMPT [DEFAULT]
  local __var=$1 __prompt=$2 __default=${3-} __reply
  printf '%s%s: ' "$__prompt" "${__default:+ [$__default]}"
  # read returns non-zero at EOF even when it read a partial line, so an answer
  # typed without a trailing newline is an answer, not missing input.
  IFS= read -r __reply || [ -n "$__reply" ] || { echo; echo "No input on stdin." >&2; exit 1; }
  printf -v "$__var" '%s' "${__reply:-$__default}"
}

ask_secret() { # ask_secret VAR PROMPT — no echo; the value becomes a podman secret
  local __var=$1 __reply
  printf '%s: ' "$2"
  IFS= read -rs __reply || [ -n "$__reply" ] || { echo; echo "No input on stdin." >&2; exit 1; }
  echo
  printf -v "$__var" '%s' "$__reply"
}

# No openssl/python dependency: the bundle is extracted on a host that has only
# podman guaranteed.
# Hex, so the value is safe to drop into .env, a URL and a sed replacement alike.
rand() { od -An -vtx1 -N"$1" /dev/urandom | tr -d ' \n'; }

backup() { [ -e "$1" ] && { mv -- "$1" "$1.bak"; echo "  kept previous $1 as $1.bak"; }; return 0; }

# ----------------------------------------------------------- prerequisites ----
# Detect, never escalate. Functions because --quadlet can be unable to do
# anything at all (no podman), and the operator is owed the whole list then, not
# just the one prerequisite that stopped the run — and because `check` reports
# the same list as FAIL/warn lines.
#
# outstanding: each a problem plus, indented below it, the command that fixes it.
# unverified:  what cannot be decided from this host at all.
detect_prerequisites() {
  outstanding=() unverified=()
  need() { outstanding+=("$1"$'\n      '"$2"); }

  command -v podman >/dev/null || need "Podman is not installed." "sudo dnf install -y podman   # or: sudo apt install -y podman"

  port_start=$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)
  [ "$port_start" -le 80 ] 2>/dev/null || need \
    "Rootless Podman cannot bind 80/443 (net.ipv4.ip_unprivileged_port_start=$port_start)." \
    "sudo install -m 0644 deploy/sysctl-99-kendo-rootless-ports.conf /etc/sysctl.d/99-kendo-rootless-ports.conf && sudo sysctl --system"

  if command -v firewall-cmd >/dev/null; then
    firewall-cmd --list-services 2>/dev/null | grep -qw https || need \
      "firewalld is not allowing http/https." \
      "sudo firewall-cmd --permanent --add-service=http --add-service=https && sudo firewall-cmd --reload"
  elif command -v ufw >/dev/null; then
    # `ufw status` refuses anyone but root, which says nothing about the rules.
    if ! ufw_status=$(ufw status 2>/dev/null); then
      unverified+=("ufw reports its rules only to root — check that \`sudo ufw status\` allows 80/443.")
    else
      case $ufw_status in
        *inactive*|*443*|*Https*|*https*) ;;
        *) need "ufw is not allowing 80/443." "sudo ufw allow 80/tcp && sudo ufw allow 443/tcp" ;;
      esac
    fi
  else
    unverified+=("No firewalld or ufw found — check whatever fronts this host allows inbound 80/443.")
  fi

  # The dedicated account is what docs/deployment.md builds the hardened path on,
  # and the account this stack should be owned by even on the quick path. Compose
  # runs as whoever invokes it, though, so linger is checked for the user that
  # will actually own the containers rather than always for `kendo`.
  owner=$(id -un)
  if id kendo >/dev/null 2>&1; then
    owner=kendo
  else
    need "No dedicated \`kendo\` user to own the containers — until there is one, they belong to $owner." \
      "sudo useradd --create-home --shell /usr/sbin/nologin kendo   # then re-run this from its home"
  fi

  [ "$(loginctl show-user "$owner" --property=Linger 2>/dev/null)" = "Linger=yes" ] || need \
    "Linger is off for $owner — the stack will not survive logout or reboot." \
    "sudo loginctl enable-linger $owner"
}

report_prerequisites() {
  detect_prerequisites
  echo
  if [ $(( ${#outstanding[@]} + ${#unverified[@]} )) -eq 0 ]; then
    echo "Host prerequisites: all five satisfied."
  else
    echo "Host prerequisites — run these yourself (this script never escalates):"
    for item in "${outstanding[@]}" "${unverified[@]}"; do echo "  - $item"; done
  fi
}

have_secret() { podman secret inspect "$1" >/dev/null 2>&1; }

# ------------------------------------------------------------------ check -----
# Advisory (#413): it reports and changes nothing, and nothing gates on it. The
# app already refuses to start on a blank secret or a localhost RP_ID
# (validate_startup_config); this covers what the app cannot see from inside its
# container — Traefik's files, DNS, the ports, the host — which otherwise surface
# as a browser error or a certificate that never arrives. Any FAIL exits 1 so it
# composes; `warn` is for what cannot be decided from here, and does not.
failures=0
ok()   { printf '  ok    %s\n' "$1"; }
warn() { printf '  warn  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# The <your-...> slots of the .example files and the RFC 2606 example domains,
# on non-comment lines: nobody can get a certificate for dojo.example.com.
placeholders() {
  sed 's/#.*//' "$1" | grep -oE '<your-[^>]*>|[a-z0-9.@-]*example\.(com|org|net)' | sort -u | tr '\n' ' ' || true
}

# env_value FILE KEY: the value Compose would read, so one pair of surrounding
# quotes put there by hand is not part of it.
env_value() {
  sed -n "s/^$2=//p" "$1" | tail -1 |
    sed -e 's/^"\(.*\)"$/\1/' -e t -e "s/^'\(.*\)'\$/\1/"
}

# Compose mounts these at /run/secrets instead of passing them as environment
# (#462). .env stays the record and secrets/ is derived from it, on setup and
# on upgrade. The directory is the operator's alone; the files are 0644 because
# a bind-mounted file keeps its host mode and the app runs as uid 1001, which
# does not own them.
write_compose_secrets() {
  local name
  ( umask 077; mkdir -p secrets )
  chmod 700 secrets
  for name in DATABASE_URL MIGRATION_DATABASE_URL JWT_SECRET SETUP_TOKEN; do
    printf '%s' "$(env_value .env "$name")" > "secrets/${name,,}"
    chmod 644 "secrets/${name,,}"
  done
}

run_check() {
  local env_file traefik_dir certs rerun
  if [ "$mode" = quadlet ]; then
    env_file=$kendo/kendo-app.env traefik_dir=$kendo/traefik certs=$kendo/traefik/certs
    rerun="./setup.sh --quadlet"
  else
    env_file=.env traefik_dir=$selfhost certs=deploy/certs rerun=./setup.sh
  fi
  local static=$traefik_dir/traefik.yml router=$traefik_dir/dynamic/kendo.yml
  echo "KendoDojoManagement — check ($([ "$mode" = quadlet ] && echo "hardened (Quadlet)" || echo "quick self-host"))"
  echo

  local f p configured=1
  for f in "$env_file" "$static" "$router"; do
    [ -f "$f" ] || { fail "$f is missing — run $rerun first"; configured=""; }
  done
  if [ -n "$configured" ]; then
    for f in "$env_file" "$router"; do
      p=$(placeholders "$f")
      if [ -z "$p" ]; then ok "$f has no placeholders"; else fail "$f still has placeholders: ${p% }"; fi
    done
    # A domain changed by hand in one file and not the other: every passkey
    # ceremony fails, and nothing in either container logs why.
    local host rp
    host=$(sed -n 's/.*Host(`\([^`]*\)`).*/\1/p' "$router" | head -1)
    rp=$(env_value "$env_file" WEBAUTHN_RP_ID)
    if [ "$host" = "$rp" ]; then ok "Traefik routes $host, the WEBAUTHN_RP_ID"
    else fail "Traefik routes ${host:-nothing} but WEBAUTHN_RP_ID is ${rp:-unset} — passkeys only work on that one host. Re-run $rerun."; fi

    # The ACME email only matters while the router asks Let's Encrypt; with a
    # bring-your-own certificate it is never sent anywhere.
    if grep -q certResolver "$router"; then
      p=$(placeholders "$static")
      if [ -z "$p" ]; then ok "$static has a real ACME email"
      else fail "$static still has placeholders: ${p% } — Let's Encrypt will not issue to them"; fi
      ! grep -q acme-staging "$static" || warn "Let's Encrypt staging: browsers will not trust the certificate. Re-run $rerun with choice 1, then delete the acme volume."
    elif [ -f "$traefik_dir/dynamic/byo-cert.yml" ]; then
      if [ -f "$certs/cert.pem" ] && [ -f "$certs/key.pem" ]; then ok "Bring-your-own certificate is in $certs/"
      else fail "byo-cert.yml serves $certs/cert.pem and $certs/key.pem, which are not there yet."; fi
      # The one BYO step setup.sh cannot do on Compose: docker-compose.yml is
      # the operator's to edit (--quadlet writes a drop-in instead).
      [ "$mode" = quadlet ] || grep -q '^[^#]*/etc/traefik/certs' docker-compose.yml 2>/dev/null ||
        fail "docker-compose.yml does not mount deploy/certs into the proxy — add \`- ./deploy/certs:/etc/traefik/certs:ro\` to its volumes."
    else
      fail "No certificate is configured (TLS was skipped), so Traefik serves its self-signed default. Re-run $rerun and pick 1-3."
    fi
  fi

  # Placeholder secrets are caught above; what is left is a blank one, and a
  # password rotated by hand in one place — the app starts, then every query is
  # refused. Podman will not read a secret back, so --quadlet can only check
  # that each one the installed units and drop-ins name exists — names read
  # from them, because a multi-variable DNS provider's drop-in is the
  # operator's own, secret names and all.
  local s absent="" names
  if [ "$mode" = quadlet ]; then
    names=$(cat "$units"/kendo-*.container "$units"/kendo-*.container.d/*.conf 2>/dev/null |
            sed -n 's/^Secret=\([^,]*\).*/\1/p' | sort -u || true)
    if [ -n "$names" ] && command -v podman >/dev/null; then
      for s in $names; do have_secret "$s" || absent+=" $s"; done
      if [ -z "$absent" ]; then ok "Every podman secret the units name exists"
      else fail "podman secret missing:$absent — re-run $rerun, or create it for your own drop-in"; fi
    fi
    # Without the daily timer, recovery-attempt IPs are cleared only when
    # kendo-app restarts, and can outlive their 30 days (#467).
    local timer=kendo-ip-retention.timer
    if [ ! -f "$HOME/.config/systemd/user/$timer" ]; then
      fail "$timer is not installed — re-run $rerun"
    elif command -v systemctl >/dev/null && ! systemctl --user is-enabled --quiet "$timer" 2>/dev/null; then
      fail "$timer is not enabled — run: systemctl --user enable --now $timer"
    else ok "$timer is installed and enabled"; fi
  elif [ -f "$env_file" ]; then
    for s in POSTGRES_PASSWORD JWT_SECRET SETUP_TOKEN; do
      [ -n "$(env_value "$env_file" "$s")" ] || absent+=" $s"
    done
    if [ -z "$absent" ]; then ok "POSTGRES_PASSWORD, JWT_SECRET and SETUP_TOKEN are set"
    else for s in $absent; do fail "$s is blank in $env_file"; done; fi
    case $(env_value "$env_file" MIGRATION_DATABASE_URL) in
      *":$(env_value "$env_file" POSTGRES_PASSWORD)@"*) ok "MIGRATION_DATABASE_URL embeds POSTGRES_PASSWORD" ;;
      *) fail "MIGRATION_DATABASE_URL does not embed POSTGRES_PASSWORD — the database will refuse the migrate service." ;;
    esac
  fi

  # The origin's host, resolved the way this box resolves it (so /etc/hosts and
  # an internal resolver count). Off-box is only a warning: behind NAT the
  # record rightly holds the router's address, and nothing here can tell.
  local domain="" addrs a here=""
  [ ! -f "$env_file" ] || domain=$(env_value "$env_file" WEBAUTHN_ORIGIN)
  domain=${domain#https://}
  case $domain in
    ''|*'<'*) ;;
    *)
      addrs=$(getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)
      for a in $addrs; do
        if hostname -I 2>/dev/null | tr ' ' '\n' | grep -qxF "$a"; then here=$a; fi
      done
      if [ -z "$addrs" ]; then fail "$domain does not resolve — give it an A/AAAA record pointing at this host."
      elif [ -n "$here" ]; then ok "$domain resolves to $here, an address on this host"
      else warn "$domain resolves to ${addrs% }, not an address on this host — right behind NAT if the router forwards 80/443 here, otherwise DNS points somewhere else."; fi ;;
  esac

  # Permission to bind is the sysctl prerequisite below; this is the other half,
  # something already listening. After an upgrade the stack itself holds both
  # ports, through rootless Podman's port forwarder.
  local port holder
  if command -v ss >/dev/null; then
    for port in 80 443; do
      holder=$(ss -ltnpH "sport = :$port" 2>/dev/null || true)
      case $holder in
        '') ok ":$port is free" ;;
        *rootlessport*|*pasta*|*slirp4netns*) ok ":$port is held by rootless Podman — this stack, if it is up" ;;
        *) holder=$(printf '%s\n' "$holder" | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | head -1)
           [ -n "$holder" ] || holder="a process this user cannot see (run check as the stack owner)"
           fail ":$port is taken by $holder — Traefik cannot bind it." ;;
      esac
    done
  else
    warn "No \`ss\` here to tell whether 80/443 are already taken."
  fi

  # Backups (#500, #502): warnings only — an unencrypted, on-host backup is
  # still a backup, and better than none.
  local offsite newest days
  if [ -z "$(backup_setting KENDO_BACKUP_RECIPIENT)" ]; then
    warn "Backups are not encrypted — set a key with ./setup.sh backup-key$mode_flag"
  elif ! command -v age >/dev/null; then
    warn "A backup key is set, but \`age\` is not installed — every backup fails until it is: $age_install"
  else ok "Backups are encrypted"; fi
  # Asked of kendo-backup.sh, the code that decides it every night, so the two
  # rules cannot drift. It reads backup.env; a setting given only through
  # Environment= in kendo-backup.service is not seen here.
  if offsite=$(bash "$backup_script" --check-offsite); then ok "$offsite"; else warn "$offsite"; fi
  # Only Quadlet has a nightly timer; on Compose a backup is taken by upgrade.
  if [ "$mode" = quadlet ]; then
    newest=$(ls -1t "$backup_dir"/kendo-*.dump "$backup_dir"/kendo-*.dump.age 2>/dev/null | head -1 || true)
    if [ -z "$newest" ]; then
      warn "No backups in $backup_dir yet — is kendo-backup.timer enabled? (docs/install/backups.md)"
    else
      days=$(( ($(date +%s) - $(stat -c %Y "$newest")) / 86400 ))
      if [ "$days" -ge 2 ]; then warn "The newest backup is $days days old — check: systemctl --user status kendo-backup"
      else ok "Newest backup: ${newest##*/}"; fi
    fi
    # A fresh dump says nothing about the remote: a copy that fails every
    # night (an expired rclone token, say) shows only as a failed unit.
    if command -v systemctl >/dev/null && systemctl --user is-failed --quiet kendo-backup.service 2>/dev/null; then
      if [ "$(systemctl --user show -P ExecMainStatus kendo-backup.service 2>/dev/null)" = 75 ]; then
        warn "The last backup could not be copied off-site — check: journalctl --user -u kendo-backup"
      else
        warn "The last backup run failed — check: systemctl --user status kendo-backup"
      fi
    fi
  fi

  detect_prerequisites
  for item in "${outstanding[@]}"; do fail "$item"; done
  for item in "${unverified[@]}"; do warn "$item"; done
  [ ${#outstanding[@]} -gt 0 ] || ok "Host prerequisites satisfied."

  echo
  if [ "$failures" -gt 0 ]; then
    echo "$failures check(s) failed. Advisory only — nothing was changed."
    return 1
  fi
  if [ "$mode" = quadlet ]; then
    echo "Green. Next: systemctl --user start kendo-traefik.service"
  else
    echo "Green. Next: podman-compose up -d"
  fi
}

# ---------------------------------------------------------------- upgrade -----
# Quick self-host only (#414). `pull && up` runs `alembic upgrade head` against
# the live database unprompted, so this puts a backup in front of it and the
# exact restore behind it. It never refuses to go ahead without a backup of its
# own making: that would block the first upgrade and train people into --force.
#
# The stack is the Compose project `kendodojo` (docker-compose.yml's `name:`);
# both podman-compose and docker compose label its containers with it.
project=kendodojo
compose_container() { # compose_container SERVICE — its container's name
  podman ps -a --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -1
}

# Take the bundle out of the image about to run, so config and image stay on
# one version axis (ADR-0004): a stale compose file must not drive a new app.
# PREV is the bundle the pinned image carried before the pull, which is what
# tells a file this release changed from an edit of the operator's (a BYO
# certificate's mount in docker-compose.yml, say). An edited file the release
# also changed is never overwritten: its new version lands next to it as .new
# and the upgrade stops before anything is recreated. The bundle carries only
# shipped files — never .env or the filled-in Traefik config — but a
# contributor's own build could, so those are skipped by name.
refresh_bundle() { # refresh_bundle PREV NEXT
  local prev=$1 next=$2 f changed="" merge=""
  while IFS= read -r f; do
    case $f in .env|"$selfhost"/traefik.yml|"$selfhost"/dynamic/*.yml) continue ;; esac
    if cmp -s "$next/$f" "$f"; then
      rm -f -- "$f.new"                     # current, or merged into exactly this
    elif [ ! -e "$f" ] || cmp -s "$prev/$f" "$f"; then
      [ ! -e "$f" ] || mv -- "$f" "$f.bak"  # untouched since the last release
      mkdir -p "$(dirname "$f")"
      # A rename, not a copy: setup.sh replaces itself here, and bash reads a
      # script as it runs — this run carries on reading setup.sh.bak.
      mv -- "$next/$f" "$f"
      changed+="  $f"$'\n'
    elif cmp -s "$f.new" "$next/$f"; then
      # Merged by hand after the last run stopped. Checked first: that run's
      # pull already moved the tag, so PREV is this release by now.
      rm -f -- "$f.new"
    elif cmp -s "$prev/$f" "$next/$f"; then
      :                                     # edited, and the release left it alone
    else
      mv -- "$next/$f" "$f.new"
      merge+="  $f.new"$'\n'
    fi
  done < <(cd "$next" && find . -type f | sed 's|^\./||' | sort)

  if [ -n "$changed" ]; then
    echo "Deployment bundle files that changed in this release (previous copies kept as .bak):"
    printf '%s' "$changed"
    case $changed in *"  .env.example"$'\n'*)
      echo "  .env.example changed: compare it with your .env for new settings." ;;
    esac
  elif [ -z "$merge" ]; then
    echo "Deployment bundle unchanged in this release."
  fi
  if [ -n "$merge" ]; then
    {
      echo
      echo "These carry edits of yours and also changed in this release; its version is"
      echo "next to each as .new:"
      printf '%s' "$merge"
      echo "Merge each into yours (or take it whole), then re-run ./setup.sh upgrade."
      echo "Nothing has been recreated: the stack still runs the previous image."
    } >&2
    exit 1
  fi
}

# Run kendo-backup.sh against this stack and print what it wrote. Its output is
# left in backup_out, and the names it was run with in backup_names, so a caller
# can say exactly how to restore or re-run it. The Quadlet defaults are the
# script's own; the Compose stack's are project-scoped.
backup_out="" backup_names="" backup_script=deploy/bin/kendo-backup.sh
run_backup() {
  if [ "$mode" = compose ]; then
    # The backup needs the database up; `up -d db` is a no-op when it already is.
    podman-compose up -d db >/dev/null
    local db
    db=$(compose_container db)
    # Compose volumes are project-scoped: `static_uploads` is kendodojo_static_uploads.
    backup_names="KENDO_DB_CONTAINER=${db:-<db container>} KENDO_UPLOADS_VOLUME=${project}_static_uploads"
    [ -n "$db" ] || { echo "No db container in the Compose project \`$project\` — run this where the stack runs." >&2; return 1; }
    podman wait --condition=healthy "$db" >/dev/null
  fi
  # Exit 75 is kendo-backup.sh's "the local backup is complete, the off-site
  # copy failed" (#502): already reported on stderr, and not a reason to stop.
  local status=0
  backup_out=$(env $backup_names bash "$backup_script") || status=$?
  [ "$status" = 0 ] || [ "$status" = 75 ] || return 1
  printf '%s\n' "$backup_out" | sed 's/^/  /'
}

run_upgrade() {
  [ -f .env ] || { echo "No .env here — run ./setup.sh first." >&2; exit 1; }
  command -v podman-compose >/dev/null || { echo "podman-compose is not installed." >&2; exit 1; }

  [ -z "$(backup_setting KENDO_BACKUP_RECIPIENT)" ] ||
    echo "Backups are encrypted: have your backup key ready in case you need to roll back."
  echo "Backing up before anything changes:"
  run_backup || { echo "Backup failed — nothing was upgraded." >&2; exit 1; }
  local names=$backup_names out=$backup_out
  local dump uploads key_note=""
  # .age when a backup key is set (#500): only its private half, which is not
  # on this host, can restore it.
  dump=$(printf '%s\n' "$out" | sed -En 's/^written: (.*\.dump(\.age)?) \(.*/\1/p')
  uploads=$(printf '%s\n' "$out" | sed -En 's/^written: (.*\.tar(\.age)?) \(.*/\1/p')
  case $dump in *.age) key_note="  (encrypted: kendo-restore.sh asks for your backup key)" ;; esac

  # The digest of what is running now, before a pull moves the tag: restoring
  # the data is only half a rollback, as the new image would migrate it again.
  local image previous
  image=$(env_value .env KENDO_IMAGE)
  image=${image:-ghcr.io/booji/kendodojomanagement:1}
  previous=$(podman image inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || true)

  # Global, not local: the EXIT trap runs after this function has returned.
  # Inside this directory so refresh_bundle's `mv`s are renames.
  tmp=$(mktemp -d .upgrade.XXXXXX)
  trap 'rm -rf -- "$tmp"' EXIT
  mkdir "$tmp/prev" "$tmp/next"
  # Before the pull moves the tag. Missing (an image removed by hand) only
  # makes refresh_bundle treat every differing file as edited: it stops, never
  # overwrites.
  podman run --rm "$image" init 2>/dev/null | tar -x -C "$tmp/prev" 2>/dev/null || true

  podman-compose pull || { echo "Pull failed — nothing past the backup was changed." >&2; exit 1; }
  podman run --rm "$image" init | tar -x -C "$tmp/next" ||
    { echo "Could not extract the bundle from $image — nothing past the backup was changed." >&2; exit 1; }
  refresh_bundle "$tmp/prev" "$tmp/next"
  # A stack set up before #462 has no secrets/ yet, and the compose file it
  # just took mounts them; re-deriving also picks up a hand edit of .env.
  write_compose_secrets

  # --force-recreate: podman-compose recreates a container only when the YAML
  # changed, and a new image under the same :1 tag is not a YAML change. And
  # it treats service_completed_successfully as merely "stopped", so a failed
  # migration does not fail `up` — migrate's exit code is read here instead.
  local code=""
  if podman-compose up -d --force-recreate; then
    code=$(podman wait "$(compose_container migrate)" 2>/dev/null || true)
  fi
  if [ "$code" != 0 ]; then
    {
      echo
      echo "Upgrade failed${code:+ (migrate exited $code)}. \`podman-compose logs migrate app\` says why."
      echo "To roll back to the backup taken above:"
      echo "  podman-compose stop app"
      echo "  $names bash deploy/bin/kendo-restore.sh $(printf '%q' "$dump")${uploads:+ $(printf '%q' "$uploads")}"
      [ -z "$key_note" ] || echo "$key_note"
      [ -z "$previous" ] || echo "  then set KENDO_IMAGE=$previous in .env — the image that was running —"
      # Not just `start app`: the restore leaves kendo_app without grants (#481).
      echo "  and: podman-compose up -d --force-recreate   # re-runs migrate, which restores the grants"
    } >&2
    exit 1
  fi
  echo
  echo "Upgraded: migrations applied and the stack recreated on $image."
  echo "The backup stays in $(dirname "$dump"). \`./setup.sh check\` confirms the rest."
}

# ------------------------------------------------------------- backup key -----
# Backups are encrypted with age to a key's public half (#500), kept in
# backup_config for kendo-backup.sh. The private half is shown here once and
# never written down on this host, so a stolen host cannot read a single
# backup — and a lost key cannot restore one, hence the confirmation.
backup_config=${KENDO_BACKUP_CONFIG:-$HOME/.config/kendo/backup.env}
backup_dir=${KENDO_BACKUP_DIR:-$HOME/backups}
mode_flag=$([ "$mode" = quadlet ] && echo " --quadlet" || true)
age_install="sudo dnf install -y age   # or: sudo apt install -y age"

# backup_setting NAME — the environment's value, else backup_config's. Asked
# of kendo-backup.sh itself, so quotes or a comment in the file mean the same
# here as to the backup.
backup_setting() { bash "$backup_script" --setting "$1"; }

# The secret only ever passes through pipes and variables: no heredoc or
# here-string near it, as bash may back those with a temporary file.
new_backup_key() {
  local secret public typed
  secret=$(age-keygen 2>/dev/null | grep '^AGE-SECRET-KEY-') || { echo "age-keygen failed — no key was set." >&2; return 1; }
  public=$(printf '%s\n' "$secret" | age-keygen -y) || { echo "age-keygen failed — no key was set." >&2; return 1; }
  echo
  echo "Backup key — shown once. Save it now in a password manager, or print it."
  echo "Without it, no backup made from now on can be restored. Name it with"
  echo "today's date, e.g. \"Kendo backup key (from $(date +%F))\"."
  echo
  printf '  %s\n' "$secret"
  echo
  while :; do
    printf 'Once it is saved, type its last 6 characters (blank to give up): '
    # Not `ask`: running out of input here means give up, not abort the run.
    IFS= read -r typed || [ -n "$typed" ] || { echo; typed=""; }
    [ -n "$typed" ] || { echo "  No key was set."; return 1; }
    [ "${typed^^}" = "${secret: -6}" ] && break
    echo "  That does not match the end of the key above — check what you saved."
  done
  mkdir -p "$(dirname "$backup_config")"
  touch "$backup_config"
  if grep -q '^KENDO_BACKUP_RECIPIENT=' "$backup_config"; then
    sed -i "s|^KENDO_BACKUP_RECIPIENT=.*|KENDO_BACKUP_RECIPIENT=$public|" "$backup_config"
  else
    printf 'KENDO_BACKUP_RECIPIENT=%s\n' "$public" >> "$backup_config"
  fi
  echo "  wrote the public half to $backup_config"
}

# A lost key, a leaked one, a volunteer handing over: a new key, then a backup
# under it straight away, so the old key stops mattering for anything new.
run_backup_key() {
  command -v age-keygen >/dev/null || { echo "\`age\` is not installed: $age_install" >&2; exit 1; }
  # Everything that could stop the backup below is checked before a key exists:
  # a key set with no backup under it is one more thing to explain.
  [ -z "${KENDO_BACKUP_RECIPIENT:-}" ] || {
    echo "KENDO_BACKUP_RECIPIENT is set in this environment and wins over $backup_config, so a new key would never be used. Unset it — and remove it from kendo-backup.service if it is there — then re-run." >&2
    exit 1
  }
  if [ "$mode" = compose ]; then
    [ -f .env ] || { echo "No .env here — run ./setup.sh first." >&2; exit 1; }
    command -v podman-compose >/dev/null || { echo "podman-compose is not installed." >&2; exit 1; }
  else
    [ -f deploy/bin/kendo-backup.sh ] || { echo "Missing deploy/bin/kendo-backup.sh — run this from the deployment bundle or a checkout." >&2; exit 1; }
  fi
  # Taken before the new backup exists, so it is exactly what the old key made.
  local older old_key
  mapfile -t older < <(ls -1d "$backup_dir"/kendo-*.dump* "$backup_dir"/kendo-uploads-*.tar* 2>/dev/null)
  old_key=$(backup_setting KENDO_BACKUP_RECIPIENT)
  new_backup_key || exit 1

  if [ "$mode" = quadlet ]; then
    # The timer runs the installed copy, and one from before #500 ignores the key.
    install -m 755 deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh "$HOME/.local/bin/"
    echo "  refreshed kendo-backup.sh and kendo-restore.sh in $HOME/.local/bin, which the timer runs"
    backup_script=$HOME/.local/bin/kendo-backup.sh
  fi

  # Before the backup, which can fail: this holds either way. With no old key,
  # backups were plaintext and never left the host, so nothing is off-site.
  local remote
  remote=$(backup_setting KENDO_BACKUP_REMOTE)
  if [ -n "$remote" ] && [ -n "$old_key" ]; then
    echo
    echo "Copies at $remote made under the old key are untouched. If it leaked, delete"
    echo "  them there, and empty the provider's trash or recycle bin too."
  fi

  echo
  echo "Backing up under the new key:"
  if ! run_backup; then
    {
      echo "The new key is set, but that backup failed. Nothing older was touched."
      echo "Once the database is up, take one:"
      echo "  ${backup_names:+$backup_names }bash $backup_script"
    } >&2
    exit 1
  fi
  [ ${#older[@]} -gt 0 ] || return 0

  echo
  echo "These backups predate the new key; an encrypted one opens only with the key it was made under:"
  printf '  %s\n' "${older[@]##*/}"
  echo "Keep them while the old key is still safe. If it leaked, delete them — and any copies elsewhere."
  local reply=""
  printf 'Delete them? [y/N]: '
  IFS= read -r reply || true
  case $reply in
    [yY]*) rm -f -- "${older[@]}"; echo "  deleted ${#older[@]} file(s)" ;;
    *) echo "  kept; they age out with the usual pruning" ;;
  esac
}

# Install offers a key rather than requiring one: skipping leaves backups as
# they were, with kendo-backup.sh warning on every run.
offer_backup_key() {
  echo
  if [ -n "$(backup_setting KENDO_BACKUP_RECIPIENT)" ]; then
    echo "Backups: kept the existing backup key ($backup_config)."
    return 0
  fi
  if ! command -v age-keygen >/dev/null; then
    echo "Backups will not be encrypted: \`age\` is not installed. Install it ($age_install),"
    echo "  then run ./setup.sh backup-key$mode_flag."
    return 0
  fi
  # Only to a person at a terminal: a scripted install's stdout is a log, and a
  # key printed there lands on disk.
  if ! { [ -t 0 ] && [ -t 1 ]; }; then
    echo "Backups are not encrypted yet: run ./setup.sh backup-key$mode_flag to set a key."
    return 0
  fi
  local reply=""
  printf 'Encrypt backups? You will be shown a key to save [Y/n]: '
  IFS= read -r reply || [ -n "$reply" ] || { echo; reply=n; }
  case $reply in
    [nN]*) echo "  Backups stay unencrypted until you run ./setup.sh backup-key$mode_flag." ;;
    *) new_backup_key || true ;;
  esac
}

case $action in
  check) run_check; exit ;;
  upgrade) run_upgrade; exit ;;
  backup-key) run_backup_key; exit ;;
esac

echo "KendoDojoManagement — $([ "$mode" = quadlet ] && echo "hardened (Quadlet)" || echo "quick self-host") setup"
echo

while :; do
  ask domain "Public domain the browser will use (bare host, no https://)"
  # RP_ID is matched against the lowercased browser host, so normalise here
  # rather than let a capital letter become a silent passkey failure.
  domain=$(printf '%s' "$domain" | tr 'A-Z' 'a-z')
  case $domain in
    *://*|*:*|*/*|*' '*|'') echo "  Bare hostname only, e.g. dojo.example.com." ;;
    *[!a-z0-9.-]*) echo "  A hostname is letters, digits, dots and hyphens only." ;;
    .*|*.|-*|*-|*..*|*.-*|*-.*) echo "  Every label must be non-empty and not start or end with a hyphen." ;;
    *.*) break ;;
    *) echo "  Needs a dot — passkeys cannot bind to a bare label." ;;
  esac
done

cat <<'MENU'

TLS:
  1) Let's Encrypt production
  2) Let's Encrypt staging   (rehearse without burning the production rate limit)
  3) Bring your own certificate
  4) Skip for now
MENU
while :; do
  ask tls_choice "Choice" 1
  case $tls_choice in 1|2|3|4) break ;; *) echo "  Answer 1, 2, 3 or 4." ;; esac
done

acme_email=""
challenge=http
dns_provider=""
case $tls_choice in
  1|2)
    cat <<'MENU'

ACME challenge:
  1) HTTP-01     (default — needs inbound port 80)
  2) TLS-ALPN-01 (needs inbound 443 only; the answer when an ISP blocks 80)
  3) DNS-01      (no inbound ports; needs provider API credentials)
MENU
    while :; do
      ask challenge_choice "Choice" 1
      case $challenge_choice in 1|2|3) break ;; *) echo "  Answer 1, 2 or 3." ;; esac
    done
    case $challenge_choice in
      2) challenge=alpn ;;
      3) challenge=dns
         # The slug lands in traefik.yml verbatim, so keep it to what a lego
         # provider name can be rather than trusting it into the YAML.
         while :; do
           ask dns_provider "lego DNS provider slug (cloudflare, route53, gandiv5, ...)"
           case $dns_provider in
             ''|*[!a-z0-9_-]*) echo "  Lowercase letters, digits, - and _ only." ;;
             *) break ;;
           esac
         done ;;
      *) challenge=http ;;
    esac
    while :; do
      ask acme_email "Email for Let's Encrypt expiry notices"
      case $acme_email in *?@?*.?*) break ;; *) echo "  That does not look like an email address." ;; esac
    done
    ;;
esac

# ---------------------------------------------------------------- .env --------
# Re-running must never silently clobber secrets: existing values are carried
# forward rather than regenerated.
# An operator who copied .env.example by hand first has placeholders, not
# secrets — those must not be carried forward or the app refuses to start.
# --quadlet never carries: its secrets live in podman, and a .env left behind by
# a Compose run in the same directory is plaintext this path deliberately avoids.
carry() { [ "$mode" = compose ] && [ -f .env ] || return 0; sed -n "s/^$1=\([^<].*\)$/\1/p" .env | head -1; }

db_password=$(carry POSTGRES_PASSWORD); [ -n "$db_password" ] || db_password=$(rand 24)
jwt_secret=$(carry JWT_SECRET);         [ -n "$jwt_secret" ]  || jwt_secret=$(rand 32)
setup_token=$(carry SETUP_TOKEN);       [ -n "$setup_token" ] || setup_token=$(rand 32)
# The app user's own password (ADR-0007), carried out of DATABASE_URL. An .env
# from before #453, whose DATABASE_URL is still the superuser's, gets a fresh
# one: re-running is the upgrade.
app_db_password=$(carry DATABASE_URL | sed -n 's|^postgresql+asyncpg://kendo_app:\([^@<]*\)@.*|\1|p')
[ -n "$app_db_password" ] || app_db_password=$(rand 24)

# The bundle knows the tag it was extracted from (ADR-0004), so the pin is never
# a guess. A checkout has no .image-tag, so an existing .env's pin is carried
# forward like the secrets are — a contributor on localhost/kendodojo:latest
# must not have a re-run revert them to the published default.
image=$(cat .image-tag 2>/dev/null || true)
[ -n "$image" ] || image=$(carry KENDO_IMAGE)

echo
if [ "$mode" = compose ]; then
  backup .env
  ( umask 077
  sed \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://kendo_app:$app_db_password@db:5432/kendo|" \
    -e "s|^MIGRATION_DATABASE_URL=.*|MIGRATION_DATABASE_URL=postgresql+asyncpg://kendo:$db_password@db:5432/kendo|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$db_password|" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=$jwt_secret|" \
    -e "s|^SETUP_TOKEN=.*|SETUP_TOKEN=$setup_token|" \
    -e "s|^WEBAUTHN_RP_ID=.*|WEBAUTHN_RP_ID=$domain|" \
    -e "s|^WEBAUTHN_ORIGIN=.*|WEBAUTHN_ORIGIN=https://$domain|" \
    -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=https://$domain|" \
    ${image:+-e "s|^KENDO_IMAGE=.*|KENDO_IMAGE=$image|"} \
    .env.example > .env
  )
  chmod 600 .env
  echo "  wrote .env (mode 600)"
  write_compose_secrets
  echo "  wrote secrets/ from it (mode 700)"
fi

# The one provider table. dns_var is the single environment variable lego reads,
# and is empty for a provider that needs several — those are left to the operator
# rather than guessed at. dns_help is the same thing said to a human.
dns_var=""
dns_help=""
dns_credentials() {
  case $dns_provider in
    cloudflare)   dns_var=CF_DNS_API_TOKEN
                  dns_help="CF_DNS_API_TOKEN (scope: Zone:DNS:Edit on this zone only)" ;;
    gandiv5)      dns_var=GANDIV5_PERSONAL_ACCESS_TOKEN; dns_help=$dns_var ;;
    digitalocean) dns_var=DO_AUTH_TOKEN;                 dns_help=$dns_var ;;
    hetzner)      dns_var=HETZNER_API_KEY;               dns_help=$dns_var ;;
    route53)      dns_help="AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION" ;;
    *)            dns_help="the variables lego documents for \`$dns_provider\`" ;;
  esac
}
[ "$challenge" = dns ] && dns_credentials

# ------------------------------------------------------------ traefik.yml -----
# Everything from the ACME CHALLENGE marker to the end of the block is ours.
challenge_block() {
  [ "$tls_choice" = 2 ] && \
    printf '      caServer: https://acme-staging-v02.api.letsencrypt.org/directory\n'
  case $challenge in
    alpn) printf '      # TLS-ALPN-01: inbound 443 only.\n      tlsChallenge: {}\n' ;;
    dns)  printf '      # DNS-01: no inbound ports; credentials come from the environment.\n'
          printf '      dnsChallenge:\n        provider: %s\n' "$dns_provider"
          printf '        resolvers:\n          - "1.1.1.1:53"\n          - "8.8.8.8:53"\n' ;;
    *)    printf '      # HTTP-01: the host must be publicly reachable on port 80.\n'
          printf '      httpChallenge:\n        entryPoint: web\n' ;;
  esac
}

write_static() { # write_static SRC DST
  backup "$2"
  awk -v email="${acme_email:-you@example.com}" -v block="$(challenge_block)" '
    /^      email: / { print "      email: " email; next }
    /ACME CHALLENGE/ { printf "%s\n", block; inblock = 1; next }
    inblock && (/^[^ ]/ || /^$/) { inblock = 0 }
    inblock { next }
    { print }
  ' "$1" > "$2"
  echo "  wrote $2"
}

# -------------------------------------------------------------- kendo.yml -----
# No resolver without Let's Encrypt: `tls: {}` serves the default certificate,
# which is byo-cert.yml's if one is in place.
write_router() { # write_router SRC DST
  backup "$2"
  awk -v domain="$domain" -v le="$([ "$tls_choice" = 1 ] || [ "$tls_choice" = 2 ] && echo 1)" '
    /^      rule: / { print "      rule: \"Host(`" domain "`)\""; next }
    !le && /^      tls:/ { print "      tls: {}"; drop = 1; next }
    drop && /certResolver/ { drop = 0; next }
    { print }
  ' "$1" > "$2"
  echo "  wrote $2"
}

copy_byo() { # copy_byo SRC DST — only when the operator brings their own cert
  [ "$tls_choice" = 3 ] || return 0
  backup "$2"
  cp "$1" "$2"
  echo "  wrote $2"
}

# ---------------------------------------------------------------- quadlet -----
# Sections 2-4 of docs/deployment.md are pure transcription — the six podman
# secrets, the ~/kendo/ tree the units mount, the units themselves — and that is
# exactly what an operator gets wrong at 11pm (#412). MIGRATION_DATABASE_URL
# embeds the postgres password, so one script owning both is what makes them
# impossible to mismatch.

put_secret() { # put_secret NAME VALUE
  printf '%s' "$2" | podman secret create "$1" - >/dev/null
  echo "  created secret $1"
}

new_setup_token=""
reload_failed="" timer_failed=""
quadlet_install() {
  command -v podman >/dev/null || {
    echo "Podman is not installed, and the hardened deployment is nothing but podman secrets and Quadlet units. Nothing was written." >&2
    report_prerequisites
    exit 1
  }
  mkdir -p "$kendo/traefik/dynamic" "$HOME/backups" "$HOME/.local/bin" "$units"

  # The password and the URL embedding it are one pair. Podman will not read a
  # secret back, so a half-present pair cannot be completed consistently —
  # refuse rather than write a URL with a password the database does not have.
  if have_secret kendo_postgres_password && have_secret kendo_migration_database_url; then
    echo "  kept existing secrets kendo_postgres_password and kendo_migration_database_url"
  elif have_secret kendo_postgres_password || have_secret kendo_migration_database_url; then
    echo "Only one of kendo_postgres_password / kendo_migration_database_url exists; they must embed the same password and neither can be read back. On a fresh install, remove both and re-run:" >&2
    echo "  podman secret rm kendo_postgres_password kendo_migration_database_url" >&2
    exit 1
  else
    put_secret kendo_postgres_password "$db_password"
    put_secret kendo_migration_database_url "postgresql+asyncpg://kendo:$db_password@kendo-db:5432/kendo"
  fi
  # The app user's login (ADR-0007) pairs with nothing: kendo-migrate sets that
  # user's password from it on every start.
  if have_secret kendo_database_url; then
    echo "  kept existing secret kendo_database_url"
  else
    put_secret kendo_database_url "postgresql+asyncpg://kendo_app:$app_db_password@kendo-db:5432/kendo"
  fi
  # A re-run must never rotate a secret out from under a running instance.
  if have_secret kendo_jwt_secret; then
    echo "  kept existing secret kendo_jwt_secret"
  else
    put_secret kendo_jwt_secret "$jwt_secret"
  fi
  # A podman secret is write-only, and this one has to reach a human: whoever
  # holds it claims the first admin account (ADR-0003). Printed once, below.
  if have_secret kendo_setup_token; then
    echo "  kept existing secret kendo_setup_token"
  else
    put_secret kendo_setup_token "$setup_token"
    new_setup_token=$setup_token
  fi

  if [ "$challenge" = dns ] && [ -n "$dns_var" ]; then
    if have_secret kendo_dns_token; then
      echo "  kept existing secret kendo_dns_token — \`podman secret rm\` it and re-run if you changed provider"
    else
      while :; do
        ask_secret dns_token "$dns_var for $dns_provider (not echoed)"
        [ -n "$dns_token" ] && break
        echo "  Empty — podman will not store an empty secret, and ACME needs this."
      done
      put_secret kendo_dns_token "$dns_token"
    fi
  fi

  # Non-sensitive app config — no umask 077 like .env gets, because every secret
  # here is a podman secret instead. The unit passes this file and nothing else,
  # so a key missing here is a key missing from the app's environment.
  backup "$kendo/kendo-app.env"
  sed \
    -e "s|^WEBAUTHN_RP_ID=.*|WEBAUTHN_RP_ID=$domain|" \
    -e "s|^WEBAUTHN_ORIGIN=.*|WEBAUTHN_ORIGIN=https://$domain|" \
    -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=https://$domain|" \
    deploy/env/kendo-app.env.example > "$kendo/kendo-app.env"
  echo "  wrote $kendo/kendo-app.env"

  write_static "$hardened/traefik.yml" "$kendo/traefik/traefik.yml"
  write_router "$hardened/dynamic/kendo.yml" "$kendo/traefik/dynamic/kendo.yml"
  copy_byo "$hardened/dynamic/byo-cert.yml.example" "$kendo/traefik/dynamic/byo-cert.yml"

  install -m 755 deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh "$HOME/.local/bin/"
  echo "  installed kendo-backup.sh and kendo-restore.sh in $HOME/.local/bin"

  cp deploy/quadlet/kendo-*.network deploy/quadlet/kendo-*.volume \
     deploy/quadlet/kendo-*.container "$units/"
  # The bundle knows the tag it came from (ADR-0004); the shipped units carry the
  # documented major pin, which is right for a release and wrong for a
  # prerelease rehearsal.
  [ -z "$image" ] || sed -i "s|^Image=ghcr.io/booji/kendodojomanagement:.*|Image=$image|" \
    "$units/kendo-app.container" "$units/kendo-migrate.container" \
    "$units/kendo-ip-retention.container"
  echo "  installed the Quadlet units in $units"
  # Quadlet generates no timers: the daily IP-retention trigger (#467) is a
  # plain user unit, enabled below once the reload has generated its service.
  install -D -m 644 deploy/systemd/kendo-ip-retention.timer \
    "$HOME/.config/systemd/user/kendo-ip-retention.timer"

  # Drop-ins rather than edits to the units: docs/install/upgrading.md tells an
  # operator to re-copy the units on upgrade, which would silently revert an edit made
  # here and leave Traefik asking for a secret or a mount that is not there.
  local dropin=$units/kendo-traefik.container.d
  mkdir -p "$dropin"
  rm -f "$dropin/20-byo-cert.conf"
  # A multi-variable provider's 10-dns-01.conf is the operator's own (#423):
  # keep it across a re-run that stays on DNS-01. Ours carry the header below.
  if [ -z "$dns_var" ]; then
    if [ "$challenge" = dns ] && [ -f "$dropin/10-dns-01.conf" ] &&
       ! grep -q 'written by setup.sh --quadlet' "$dropin/10-dns-01.conf"; then
      echo "  kept your $dropin/10-dns-01.conf"
    else
      rm -f "$dropin/10-dns-01.conf"
    fi
  else
    cat > "$dropin/10-dns-01.conf" <<DROPIN
# DNS-01 credentials for $dns_provider, written by setup.sh --quadlet (#412).
[Container]
Environment=${dns_var}_FILE=/run/secrets/dns_token
Secret=kendo_dns_token,type=mount,target=dns_token
DROPIN
    echo "  wrote $dropin/10-dns-01.conf"
  fi
  if [ "$tls_choice" = 3 ]; then
    mkdir -p "$kendo/traefik/certs"
    cat > "$dropin/20-byo-cert.conf" <<'DROPIN'
# Bring-your-own certificate, written by setup.sh --quadlet (#412). The :Z label
# is required: this is a host bind mount, which SELinux does not auto-label.
[Container]
Volume=%h/kendo/traefik/certs:/etc/traefik/certs:ro,Z
DROPIN
    echo "  wrote $dropin/20-byo-cert.conf"
  fi

  # Quadlet generates the systemd units from these files on reload. Without a
  # user session (`su - kendo` rather than `machinectl shell kendo@`) this is the
  # step that fails, and it is the one worth naming when it does.
  systemctl --user daemon-reload || reload_failed=1
  [ -n "$reload_failed" ] ||
    systemctl --user enable --now kendo-ip-retention.timer || timer_failed=1
}

if [ "$mode" = compose ]; then
  write_static "$selfhost/traefik.yml.example" "$selfhost/traefik.yml"
  write_router "$selfhost/dynamic/kendo.yml.example" "$selfhost/dynamic/kendo.yml"
  copy_byo "$selfhost/dynamic/byo-cert.yml.example" "$selfhost/dynamic/byo-cert.yml"
else
  quadlet_install
fi

report_prerequisites
offer_backup_key

echo
case $tls_choice in
  2) echo "Staging certificates are untrusted by browsers. Re-run with choice 1, then" \
          "delete the acme volume, once the domain resolves." ;;
  3) if [ "$mode" = quadlet ]; then
       echo "Still outstanding: put cert.pem and key.pem in $kendo/traefik/certs/."
       echo "  The bind mount for them is already in place (the 20-byo-cert.conf drop-in)."
     else
       echo "Still outstanding: put cert.pem and key.pem in deploy/certs/, and add"
       echo "      - ./deploy/certs:/etc/traefik/certs:ro"
       echo "  to the proxy service's volumes in docker-compose.yml."
     fi ;;
  4) echo "Still outstanding: no certificate is configured. Traefik will serve its own"
     echo "  self-signed default. Re-run and pick 1-3 before going live." ;;
esac
# --quadlet already wired up a single-token provider: the secret exists and the
# drop-in names the variable. Only providers lego reads several variables for are
# left to the operator there; on Compose the credentials are always theirs to set.
if [ "$challenge" = dns ] && { [ "$mode" = compose ] || [ -z "$dns_var" ]; }; then cat <<DNS
DNS-01 needs credentials in the proxy container's environment. For $dns_provider:
  $dns_help
DNS
[ "$mode" = quadlet ] && cat <<DROPIN
Put them in $units/kendo-traefik.container.d/10-dns-01.conf as a podman secret
each (a drop-in, so re-copying the units on upgrade does not revert it):
  [Container]
  Environment=<VAR>_FILE=/run/secrets/<target>
  Secret=<secret-name>,type=mount,target=<target>
DROPIN
fi

echo
if [ "$mode" = quadlet ]; then
  [ -z "$reload_failed" ] || echo "FIRST: \`systemctl --user daemon-reload\` failed, so no units have been generated
  yet. Run it, then \`systemctl --user enable --now kendo-ip-retention.timer\`, from
  a \`machinectl shell kendo@\` session — \`su - kendo\` leaves systemctl --user
  broken — before anything below will work.
"
  [ -z "$timer_failed" ] || echo "NOTE: \`systemctl --user enable --now kendo-ip-retention.timer\` failed, so
  recovery-attempt IPs are only cleared when kendo-app restarts. Run it again from
  a \`machinectl shell kendo@\` session and read the error it gives.
"
  echo "Next: ./setup.sh check --quadlet   (every FAIL names its fix; green means ready)"
  echo "      systemctl --user start kendo-traefik.service   (Requires= pulls in app -> migrate -> db)"
  echo "      already running? systemctl --user restart kendo-traefik kendo-app   (a reload alone"
  echo "      regenerates the units; the containers keep their old config until they restart)"
  echo "      systemctl --user status kendo-db kendo-migrate kendo-app kendo-traefik --no-pager"
  echo "      then open https://$domain"
  echo "Backups are not installed — see docs/install/backups.md for the timer."
  if [ -n "$new_setup_token" ]; then
    echo
    echo "Setup token — claims the first admin account, shown once (a podman secret"
    echo "cannot be read back). Hand it over out of band; lost means rotate, not recover:"
    echo "  $new_setup_token"
  fi
else
  echo "Next: ./setup.sh check   (every FAIL names its fix; green means ready)"
  echo "      podman-compose up -d   (then open https://$domain)"
  echo "The SETUP_TOKEN in .env claims the first admin account — hand it over out of band."
fi
