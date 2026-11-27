#!/usr/bin/env bash
# First-run configuration (#411, #412).
#
#   podman run --rm ghcr.io/booji/kendodojomanagement:0.1 init | tar -x
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

# How rootless Traefik gets 80/443 on --quadlet (#575): the sysctl, or a
# firewalld forward from 80/443 to 8080/8443. The drop-in is the record of the
# choice: an upgrade re-copies the unit and leaves its drop-ins alone.
port_forward_dropin=$units/kendo-traefik.container.d/30-port-forward.conf
port_forward=""
[ "$mode" != quadlet ] || [ ! -f "$port_forward_dropin" ] || port_forward=1

if [ "$mode" = quadlet ]; then
  required=(deploy/env/kendo-app.env.example "$hardened/traefik.yml"
            "$hardened/dynamic/kendo.yml" "$hardened/dynamic/byo-cert.yml.example"
            deploy/quadlet/kendo-app.container deploy/quadlet/kendo-edge.network
            deploy/quadlet/kendo-db-data.volume
            deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh)
else
  required=(.env.example deploy/env/kendo-app.env.example "$selfhost/traefik.yml.example"
            "$selfhost/dynamic/kendo.yml.example" deploy/bin/kendo-backup.sh)
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

  # The port forward keeps ports < 1024 privileged: Traefik binds 8080/8443.
  port_start=$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)
  [ -n "$port_forward" ] || [ "$port_start" -le 80 ] 2>/dev/null || need \
    "Rootless Podman cannot bind 80/443 (net.ipv4.ip_unprivileged_port_start=$port_start)." \
    "echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-kendo-rootless-ports.conf && sudo sysctl --system"

  # The rules that let traffic in are those of the public (default-route)
  # interface's zone, which need not be the default zone; an interface firewalld
  # has not placed is in the default zone. Checked there, and fixed there.
  fw_zone=""
  if command -v firewall-cmd >/dev/null; then
    fw_iface=$(ip route show default 2>/dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit } }' || true)
    fw_zone=$(firewall-cmd --get-zone-of-interface="$fw_iface" 2>/dev/null) ||
      fw_zone=$(firewall-cmd --get-default-zone 2>/dev/null) || fw_zone=""
  fi
  fw="firewall-cmd${fw_zone:+ --zone=$fw_zone}"
  forward_cmd="sudo $fw --permanent --add-forward-port=port=80:proto=tcp:toport=8080 --add-forward-port=port=443:proto=tcp:toport=8443 && sudo firewall-cmd --reload"

  # Both firewalls answer root alone (polkit for firewalld), and check runs as
  # `kendo`: a refused query says nothing about the rules (#576).
  if command -v firewall-cmd >/dev/null; then
    if ! fw_services=$(firewall-cmd ${fw_zone:+"--zone=$fw_zone"} --list-services 2>/dev/null); then
      fw_unseen="firewalld reports its rules only to root — from an admin account, check that \`sudo $fw --list-services\` includes http and https"
      if [ -z "$port_forward" ]; then
        unverified+=("$fw_unseen.")
      else
        unverified+=("$fw_unseen, and that \`sudo $fw --list-forward-ports\` forwards 80 to 8080 and 443 to 8443; if not:"$'\n      '"$forward_cmd")
      fi
    else
      printf '%s\n' "$fw_services" | grep -qw https || need \
        "firewalld is not allowing http/https." \
        "sudo $fw --permanent --add-service=http --add-service=https && sudo firewall-cmd --reload"
      if [ -n "$port_forward" ]; then
        fw_forwards=$(firewall-cmd ${fw_zone:+"--zone=$fw_zone"} --list-forward-ports 2>/dev/null || true)
        printf '%s\n' "$fw_forwards" | grep -q '^port=80:proto=tcp:toport=8080:' &&
          printf '%s\n' "$fw_forwards" | grep -q '^port=443:proto=tcp:toport=8443:' || need \
          "firewalld is not forwarding 80/443 to 8080/8443, where Traefik listens." "$forward_cmd"
      fi
    fi
  elif [ -n "$port_forward" ]; then
    need "firewalld is not installed, and the port forward from 80/443 to Traefik needs it." \
      "sudo dnf install -y firewalld && sudo systemctl enable --now firewalld && $forward_cmd"
  elif command -v ufw >/dev/null; then
    if ! ufw_status=$(ufw status 2>/dev/null); then
      unverified+=("ufw reports its rules only to root — from an admin account, check that \`sudo ufw status\` allows 80/443.")
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

# On Quadlet this runs as `kendo`, which has no sudo, so every fix is run from
# another account. Compose runs as the operator, who may have it.
if [ "$mode" = quadlet ]; then
  prerequisites_header="Host prerequisites — run these from an admin account, not as \`kendo\` (it has no sudo; this script never escalates):"
else
  prerequisites_header="Host prerequisites — run these yourself (this script never escalates):"
fi

report_prerequisites() {
  detect_prerequisites
  echo
  if [ $(( ${#outstanding[@]} + ${#unverified[@]} )) -eq 0 ]; then
    echo "Host prerequisites: all five satisfied."
  else
    echo "$prerequisites_header"
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
  # env_file holds the app settings on both paths; compose_env is the Compose
  # stack's .env, its secrets and database logins (#603).
  local env_file compose_env="" traefik_dir certs rerun
  if [ "$mode" = quadlet ]; then
    env_file=$kendo/kendo-app.env traefik_dir=$kendo/traefik certs=$kendo/traefik/certs
    rerun="./setup.sh --quadlet"
  else
    env_file=kendo-app.env compose_env=.env traefik_dir=$selfhost certs=deploy/certs rerun=./setup.sh
  fi
  local static=$traefik_dir/traefik.yml router=$traefik_dir/dynamic/kendo.yml
  echo "KendoDojoManagement — check ($([ "$mode" = quadlet ] && echo "hardened (Quadlet)" || echo "quick self-host"))"
  echo

  local f p configured=1
  for f in $compose_env "$env_file" "$static" "$router"; do
    [ -f "$f" ] || { fail "$f is missing — run $rerun first"; configured=""; }
  done
  if [ -n "$configured" ]; then
    for f in $compose_env "$env_file" "$router"; do
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
        fail "docker-compose.yml does not mount deploy/certs into the proxy — add \`- ./deploy/certs:/etc/traefik/certs:ro,z\` to its volumes."
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
    # A pin edited in one unit only would migrate with one image and serve
    # with another (#604).
    local pins
    pins=$(sed -n 's/^Image=//p' "$units"/kendo-app.container "$units"/kendo-migrate.container \
           "$units"/kendo-ip-retention.container 2>/dev/null | sort -u || true)
    [ "$(printf '%s\n' "$pins" | grep -c .)" -le 1 ] ||
      warn "The Release units pin different images: $(printf '%s\n' "$pins" | paste -sd, - | sed 's/,/, /g') — pin all three alike (docs/install/upgrading.md)"
    # Without the daily timer, recovery-attempt IPs are cleared only when
    # kendo-app restarts, and can outlive their 30 days (#467).
    local timer=kendo-ip-retention.timer
    if [ ! -f "$HOME/.config/systemd/user/$timer" ]; then
      fail "$timer is not installed — re-run $rerun"
    elif command -v systemctl >/dev/null && ! systemctl --user is-enabled --quiet "$timer" 2>/dev/null; then
      fail "$timer is not enabled — run: systemctl --user enable --now $timer"
    else ok "$timer is installed and enabled"; fi
  elif [ -f "$compose_env" ]; then
    for s in POSTGRES_PASSWORD JWT_SECRET SETUP_TOKEN; do
      [ -n "$(env_value "$compose_env" "$s")" ] || absent+=" $s"
    done
    if [ -z "$absent" ]; then ok "POSTGRES_PASSWORD, JWT_SECRET and SETUP_TOKEN are set"
    else for s in $absent; do fail "$s is blank in $compose_env"; done; fi
    case $(env_value "$compose_env" MIGRATION_DATABASE_URL) in
      *":$(env_value "$compose_env" POSTGRES_PASSWORD)@"*) ok "MIGRATION_DATABASE_URL embeds POSTGRES_PASSWORD" ;;
      *) fail "MIGRATION_DATABASE_URL does not embed POSTGRES_PASSWORD — the database will refuse the migrate service." ;;
    esac
  fi
  # restart: always covers a crash; after a reboot rootless Podman has no
  # daemon, and only podman-restart.service starts the stack again (#582).
  if [ "$mode" != quadlet ] && command -v systemctl >/dev/null; then
    if systemctl --user is-enabled --quiet podman-restart.service 2>/dev/null; then
      ok "podman-restart.service is enabled — the stack comes back after a reboot"
    else
      fail "podman-restart.service is not enabled, so the stack stays down after a reboot — run: systemctl --user enable podman-restart.service"
    fi
  fi

  # On an enforcing host a bind mount with no z/Z relabel leaves the container
  # unable to read the user_home_t file behind it, so `up` fails (#635).
  if [ "$mode" != quadlet ] && [ -f docker-compose.yml ] && command -v selinuxenabled >/dev/null && selinuxenabled; then
    local mount bare
    bare=$(sed -e 's/#.*//' -e 's/[[:space:]"]*$//' docker-compose.yml |
           sed -n 's/^[[:space:]]*-[[:space:]]*"\{0,1\}\([.~/][^:]*:.*\)/\1/p' |
           grep -vE ':([^:]*,)?[zZ](,[^:]*)?$' || true)
    # A top-level file secret is a bind mount that takes no relabel option.
    ! grep -q '^secrets:' docker-compose.yml || bare+=${bare:+$'\n'}"the top-level secrets: files"
    if [ -z "$bare" ]; then ok "Every bind mount in docker-compose.yml is relabelled for SELinux"
    else
      while IFS= read -r mount; do
        fail "SELinux will block the containers from reading $mount — add ,z to its options (or take the release's docker-compose.yml)"
      done <<< "$bare"
    fi
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
  local port holder ports="80 443"
  [ -z "$port_forward" ] || ports="8080 8443"
  if command -v ss >/dev/null; then
    for port in $ports; do
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
    warn "No \`ss\` here to tell whether ${ports/ //} are already taken."
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
        warn "The last backup could not be copied off-site — check, from your admin account: sudo journalctl _UID=$(id -u kendo) _SYSTEMD_USER_UNIT=kendo-backup.service"
      else
        warn "The last backup run failed — check: systemctl --user status kendo-backup"
      fi
    fi
  fi

  detect_prerequisites
  [ $(( ${#outstanding[@]} + ${#unverified[@]} )) -eq 0 ] || echo "$prerequisites_header"
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
# It never touches a deployment file either (#604): once installed they are the
# operator's, and a release that changes one lists it as an Operator action.
#
# The stack is the Compose project `kendodojo` (docker-compose.yml's `name:`);
# both podman-compose and docker compose label its containers with it.
project=kendodojo
compose_container() { # compose_container SERVICE — its container's name
  podman ps -a --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -1
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
  # A host set up by an rc keeps its app settings in .env, and the compose file
  # this upgrade brings reads them from kendo-app.env (#603): going on would
  # recreate the app without them.
  [ -f kendo-app.env ] || {
    echo "No kendo-app.env here: the app's settings now live in it, not in .env." >&2
    echo "Split .env once as docs/install/upgrading.md says (\"From a release candidate\")," >&2
    echo "then re-run ./setup.sh upgrade. Nothing was changed." >&2
    exit 1
  }
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
  image=${image:-ghcr.io/booji/kendodojomanagement:0.1}
  previous=$(podman image inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || true)

  podman-compose pull || { echo "Pull failed — nothing past the backup was changed." >&2; exit 1; }
  # Derived from .env, not installed config: re-deriving picks up a hand edit.
  write_compose_secrets

  # --force-recreate: podman-compose recreates a container only when the YAML
  # changed, and a new image under the same pinned tag is not a YAML change. And
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

if [ "$mode" = quadlet ]; then
  cat <<'MENU'
How Traefik receives ports 80/443 (docs/deployment.md §1.2):
  1) sysctl: let any unprivileged process bind ports >= 80
  2) firewalld port forward: Traefik binds 8080/8443, firewalld redirects 80/443 to them
MENU
  while :; do
    ask ports_choice "Choice" "$([ -n "$port_forward" ] && echo 2 || echo 1)"
    case $ports_choice in 1) port_forward=""; break ;; 2) port_forward=1; break ;; *) echo "  Answer 1 or 2." ;; esac
  done
  echo
fi

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

# ------------------------------------------------------- kendo-app.env --------
# The app settings, from the one example both paths share (#603). No umask 077
# like .env gets: every secret is a mounted file instead. Compose and the
# Quadlet unit alike pass this whole file, so a key the example gains reaches
# the app without a compose or unit change.
# A re-run keeps the operator's settings (#603): every key the previous file
# sets carries over, its own keys included, and only the domain answer and
# keys the example gained are new.
write_app_env() { # write_app_env DST
  local prev=/dev/null
  [ ! -e "$1" ] || prev="$1.bak"
  backup "$1"
  sed \
    -e "s|^WEBAUTHN_RP_ID=.*|WEBAUTHN_RP_ID=$domain|" \
    -e "s|^WEBAUTHN_ORIGIN=.*|WEBAUTHN_ORIGIN=https://$domain|" \
    -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=https://$domain|" \
    deploy/env/kendo-app.env.example |
  awk -F= -v answered="WEBAUTHN_RP_ID WEBAUTHN_ORIGIN CORS_ORIGINS" '
    BEGIN { split(answered, a, " "); for (i in a) skip[a[i]] = 1 }
    { key = $1; sub(/^[ \t]+/, "", key); sub(/[ \t]+$/, "", key) }
    /^[ \t]*#/ || !index($0, "=") || key in skip { if (FILENAME == ARGV[1]) next; print; next }
    FILENAME == ARGV[1] { if (!(key in kept)) order[++n] = key; kept[key] = $0; next }
    key in kept { print kept[key]; done[key] = 1; next }
    { print }
    END { for (i = 1; i <= n; i++) if (!(order[i] in done)) print kept[order[i]] }
  ' "$prev" - > "$1"
  echo "  wrote $1"
}

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
# The db's zone, kept like the app's TZ in kendo-app.env so the two stay alike.
tz=$(carry TZ)

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
    ${image:+-e "s|^KENDO_IMAGE=.*|KENDO_IMAGE=$image|"} \
    ${tz:+-e "s|^TZ=.*|TZ=$tz|"} \
    .env.example > .env
  )
  chmod 600 .env
  echo "  wrote .env (mode 600)"
  write_compose_secrets
  echo "  wrote secrets/ from it (mode 700)"
  write_app_env kendo-app.env
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
reload_failed="" failed_timers=()
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

  # The unit passes this file and nothing else, so a key missing here is a key
  # missing from the app's environment.
  write_app_env "$kendo/kendo-app.env"

  write_static "$hardened/traefik.yml" "$kendo/traefik/traefik.yml"
  write_router "$hardened/dynamic/kendo.yml" "$kendo/traefik/dynamic/kendo.yml"
  copy_byo "$hardened/dynamic/byo-cert.yml.example" "$kendo/traefik/dynamic/byo-cert.yml"

  install -m 755 deploy/bin/kendo-backup.sh deploy/bin/kendo-restore.sh "$HOME/.local/bin/"
  echo "  installed kendo-backup.sh and kendo-restore.sh in $HOME/.local/bin"

  cp deploy/quadlet/kendo-*.network deploy/quadlet/kendo-*.volume \
     deploy/quadlet/kendo-*.container "$units/"
  # The bundle knows the tag it came from (ADR-0004); the shipped units carry the
  # documented release-line pin, which is right for a release and wrong for a
  # prerelease rehearsal.
  [ -z "$image" ] || sed -i "s|^Image=ghcr.io/booji/kendodojomanagement:.*|Image=$image|" \
    "$units/kendo-app.container" "$units/kendo-migrate.container" \
    "$units/kendo-ip-retention.container"
  echo "  installed the Quadlet units in $units"
  # Quadlet generates no timers: the daily IP-retention trigger (#467) and the
  # nightly backup (#576) are plain user units, enabled below once the reload
  # has generated the services they need.
  local f
  for f in kendo-ip-retention.timer kendo-backup.service kendo-backup.timer; do
    install -D -m 644 "deploy/systemd/$f" "$HOME/.config/systemd/user/$f"
  done

  # Drop-ins rather than edits to the units: an Operator action that hands over a
  # new unit (docs/install/upgrading.md) would otherwise drop an edit made here
  # and leave Traefik asking for a secret or a mount that is not there.
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
  if [ -n "$port_forward" ]; then
    cat > "$port_forward_dropin" <<'DROPIN'
# Traefik behind a firewalld forward from 80/443, written by setup.sh --quadlet
# (#575). The empty PublishPort= clears the unit's 80:80 and 443:443 (a drop-in
# appends otherwise); needs Podman 5.0+, as every Quadlet drop-in does.
[Container]
PublishPort=
PublishPort=8080:80
PublishPort=8443:443
DROPIN
    echo "  wrote $port_forward_dropin"
  else
    rm -f "$port_forward_dropin"
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
  # user session (`su - kendo` rather than `machinectl shell kendo@ /bin/bash`)
  # this is the step that fails, and it is the one worth naming when it does.
  systemctl --user daemon-reload || reload_failed=1
  if [ -z "$reload_failed" ]; then
    for f in kendo-ip-retention.timer kendo-backup.timer; do
      systemctl --user enable --now "$f" || failed_timers+=("$f")
    done
  fi
}

if [ "$mode" = compose ]; then
  write_static "$selfhost/traefik.yml.example" "$selfhost/traefik.yml"
  write_router "$selfhost/dynamic/kendo.yml.example" "$selfhost/dynamic/kendo.yml"
  copy_byo "$selfhost/dynamic/byo-cert.yml.example" "$selfhost/dynamic/byo-cert.yml"
  # restart: always covers a crash; after a reboot rootless Podman has no
  # daemon, and only podman-restart.service starts the stack again (#582).
  # A user unit, so no sudo; enabling it twice changes nothing.
  if command -v systemctl >/dev/null; then
    restart_unit=enabled
    systemctl --user enable podman-restart.service || restart_unit=failed
  fi
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
       echo "      - ./deploy/certs:/etc/traefik/certs:ro,z"
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
each (a drop-in, so taking a new unit from a release does not revert it):
  [Container]
  Environment=<VAR>_FILE=/run/secrets/<target>
  Secret=<secret-name>,type=mount,target=<target>
DROPIN
fi

echo
if [ "$mode" = quadlet ]; then
  [ -z "$reload_failed" ] || echo "FIRST: \`systemctl --user daemon-reload\` failed, so no units have been generated
  yet. Run it, then \`systemctl --user enable --now kendo-ip-retention.timer
  kendo-backup.timer\`, from
  a \`machinectl shell kendo@ /bin/bash\` session — \`su - kendo\` leaves systemctl --user
  broken — before anything below will work.
"
  [ ${#failed_timers[@]} -eq 0 ] || echo "NOTE: \`systemctl --user enable --now ${failed_timers[*]}\` failed, so
  that work is not scheduled: without kendo-ip-retention.timer recovery-attempt IPs
  are only cleared when kendo-app restarts, and without kendo-backup.timer no backups
  are taken. Run it again from a \`machinectl shell kendo@ /bin/bash\` session and
  read the error it gives.
"
  echo "Next: ./setup.sh check --quadlet   (every FAIL names its fix; green means ready)"
  echo "      systemctl --user start kendo-traefik.service   (Requires= pulls in app -> migrate -> db)"
  echo "      already running? systemctl --user restart kendo-traefik kendo-app   (a reload alone"
  echo "      regenerates the units; the containers keep their old config until they restart)"
  echo "      systemctl --user status kendo-db kendo-migrate kendo-app kendo-traefik --no-pager"
  echo "      then open https://$domain"
  [ -n "$reload_failed" ] || [[ " ${failed_timers[*]} " == *" kendo-backup.timer "* ]] ||
    echo "Backups: kendo-backup.timer is enabled — into ~/backups on its schedule (docs/install/backups.md)."
  if [ -n "$new_setup_token" ]; then
    echo
    echo "Setup token — claims the first admin account, shown once (a podman secret"
    echo "cannot be read back). Hand it over out of band; lost means rotate, not recover:"
    echo "  $new_setup_token"
  fi
else
  case ${restart_unit:-} in
    enabled) echo "Reboots: podman-restart.service is enabled — the stack comes back after a reboot." ;;
    failed) echo "NOTE: \`systemctl --user enable podman-restart.service\` failed, so the stack
  stays down after a reboot. Run it again and read the error it gives.
" ;;
  esac
  echo "Next: ./setup.sh check   (every FAIL names its fix; green means ready)"
  echo "      podman-compose up -d   (then open https://$domain)"
  echo "The SETUP_TOKEN in .env claims the first admin account — hand it over out of band."
fi
