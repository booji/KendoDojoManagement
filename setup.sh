#!/usr/bin/env bash
# First-run configuration (#411, #412).
#
#   podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x
#   ./setup.sh              # quick self-host: Compose + .env
#   ./setup.sh --quadlet    # hardened: podman secrets + ~/kendo + Quadlet units
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
case "${1-}${2+ $2}" in
  '') ;;
  --quadlet) mode=quadlet ;;
  *) echo "Usage: $0 [--quadlet]" >&2; exit 2 ;;
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
  required=(.env.example "$selfhost/traefik.yml.example" "$selfhost/dynamic/kendo.yml.example")
fi
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
    -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://kendo:$db_password@db:5432/kendo|" \
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

# ----------------------------------------------------------- prerequisites ----
# Detect and print, never escalate. A function because --quadlet can be unable
# to do anything at all (no podman), and the operator is owed the whole list
# then, not just the one prerequisite that stopped the run.
report_prerequisites() {
  outstanding=()
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
    ufw status 2>/dev/null | grep -q '443\|Https\|https' || need \
      "ufw is not allowing 80/443." \
      "sudo ufw allow 80/tcp && sudo ufw allow 443/tcp"
  else
    need "No firewalld or ufw found — check whatever fronts this host allows inbound 80/443." "(nothing to run here)"
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

  echo
  if [ ${#outstanding[@]} -eq 0 ]; then
    echo "Host prerequisites: all five satisfied."
  else
    echo "Host prerequisites — run these yourself (this script never escalates):"
    for item in "${outstanding[@]}"; do echo "  - $item"; done
  fi

}

# ---------------------------------------------------------------- quadlet -----
# Sections 2-4 of docs/deployment.md are pure transcription — the five podman
# secrets, the ~/kendo/ tree the units mount, the units themselves — and that is
# exactly what an operator gets wrong at 11pm (#412). DATABASE_URL embeds the
# postgres password, so one script owning both is what makes them impossible to
# mismatch.

have_secret() { podman secret inspect "$1" >/dev/null 2>&1; }

put_secret() { # put_secret NAME VALUE
  printf '%s' "$2" | podman secret create "$1" - >/dev/null
  echo "  created secret $1"
}

new_setup_token=""
reload_failed=""
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
  if have_secret kendo_postgres_password && have_secret kendo_database_url; then
    echo "  kept existing secrets kendo_postgres_password and kendo_database_url"
  elif have_secret kendo_postgres_password || have_secret kendo_database_url; then
    echo "Only one of kendo_postgres_password / kendo_database_url exists; they must embed the same password and neither can be read back. Remove both and re-run:" >&2
    echo "  podman secret rm kendo_postgres_password kendo_database_url" >&2
    exit 1
  else
    put_secret kendo_postgres_password "$db_password"
    put_secret kendo_database_url "postgresql+asyncpg://kendo:$db_password@kendo-db:5432/kendo"
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
    "$units/kendo-app.container" "$units/kendo-migrate.container"
  echo "  installed the Quadlet units in $units"

  # Drop-ins rather than edits to the units: docs/deployment.md tells an operator
  # to re-copy the units on upgrade, which would silently revert an edit made
  # here and leave Traefik asking for a secret or a mount that is not there.
  local dropin=$units/kendo-traefik.container.d
  mkdir -p "$dropin"
  rm -f "$dropin/10-dns-01.conf" "$dropin/20-byo-cert.conf"
  if [ -n "$dns_var" ]; then
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
}

if [ "$mode" = compose ]; then
  write_static "$selfhost/traefik.yml.example" "$selfhost/traefik.yml"
  write_router "$selfhost/dynamic/kendo.yml.example" "$selfhost/dynamic/kendo.yml"
  copy_byo "$selfhost/dynamic/byo-cert.yml.example" "$selfhost/dynamic/byo-cert.yml"
else
  quadlet_install
fi

report_prerequisites

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
  yet. Run it from a \`machinectl shell kendo@\` session — \`su - kendo\` leaves
  systemctl --user broken — before anything below will work.
"
  echo "Next: systemctl --user start kendo-traefik.service   (Requires= pulls in app -> migrate -> db)"
  echo "      already running? systemctl --user restart kendo-traefik kendo-app   (a reload alone"
  echo "      regenerates the units; the containers keep their old config until they restart)"
  echo "      systemctl --user status kendo-db kendo-migrate kendo-app kendo-traefik --no-pager"
  echo "      then open https://$domain"
  echo "Backups are not installed — see section 6 of docs/deployment.md for the timer."
  if [ -n "$new_setup_token" ]; then
    echo
    echo "Setup token — claims the first admin account, shown once (a podman secret"
    echo "cannot be read back). Hand it over out of band; lost means rotate, not recover:"
    echo "  $new_setup_token"
  fi
else
  echo "Next: podman-compose up -d   (then open https://$domain)"
  echo "The SETUP_TOKEN in .env claims the first admin account — hand it over out of band."
fi
