#!/usr/bin/env bash
# First-run configuration for the quick self-host (#411).
#
#   podman run --rm ghcr.io/booji/kendodojomanagement:1 init | tar -x
#   ./setup.sh
#
# Writes .env, deploy/traefik/selfhost/traefik.yml and
# deploy/traefik/selfhost/dynamic/kendo.yml from their .example files, generates
# the three secrets, and derives WEBAUTHN_RP_ID / WEBAUTHN_ORIGIN / CORS_ORIGINS
# from one domain answer — an RP_ID typo is the whole "passkeys silently don't
# work" failure class.
#
# Unprivileged: it never escalates. Host prerequisites are detected and the
# exact `sudo` command printed for the operator to run.
set -euo pipefail

cd "$(dirname "$0")"
selfhost=deploy/traefik/selfhost

for f in .env.example "$selfhost/traefik.yml.example" "$selfhost/dynamic/kendo.yml.example"; do
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

# No openssl/python dependency: the bundle is extracted on a host that has only
# podman guaranteed.
# Hex, so the value is safe to drop into .env, a URL and a sed replacement alike.
rand() { od -An -vtx1 -N"$1" /dev/urandom | tr -d ' \n'; }

backup() { [ -e "$1" ] && { mv -- "$1" "$1.bak"; echo "  kept previous $1 as $1.bak"; }; return 0; }

echo "KendoDojoManagement — quick self-host setup"
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
carry() { [ -f .env ] || return 0; sed -n "s/^$1=\([^<].*\)$/\1/p" .env | head -1; }

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

backup "$selfhost/traefik.yml"
awk -v email="${acme_email:-you@example.com}" -v block="$(challenge_block)" '
  /^      email: / { print "      email: " email; next }
  /ACME CHALLENGE/ { printf "%s\n", block; inblock = 1; next }
  inblock && (/^[^ ]/ || /^$/) { inblock = 0 }
  inblock { next }
  { print }
' "$selfhost/traefik.yml.example" > "$selfhost/traefik.yml"
echo "  wrote $selfhost/traefik.yml"

# -------------------------------------------------------------- kendo.yml -----
# No resolver without Let's Encrypt: `tls: {}` serves the default certificate,
# which is byo-cert.yml's if one is in place.
backup "$selfhost/dynamic/kendo.yml"
awk -v domain="$domain" -v le="$([ "$tls_choice" = 1 ] || [ "$tls_choice" = 2 ] && echo 1)" '
  /^      rule: / { print "      rule: \"Host(`" domain "`)\""; next }
  !le && /^      tls:/ { print "      tls: {}"; drop = 1; next }
  drop && /certResolver/ { drop = 0; next }
  { print }
' "$selfhost/dynamic/kendo.yml.example" > "$selfhost/dynamic/kendo.yml"
echo "  wrote $selfhost/dynamic/kendo.yml"

if [ "$tls_choice" = 3 ]; then
  backup "$selfhost/dynamic/byo-cert.yml"
  cp "$selfhost/dynamic/byo-cert.yml.example" "$selfhost/dynamic/byo-cert.yml"
  echo "  wrote $selfhost/dynamic/byo-cert.yml"
fi

# ----------------------------------------------------------- prerequisites ----
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

echo
case $tls_choice in
  2) echo "Staging certificates are untrusted by browsers. Re-run with choice 1, then" \
          "delete the acme volume, once the domain resolves." ;;
  3) echo "Still outstanding: put cert.pem and key.pem in deploy/certs/, and add"
     echo "      - ./deploy/certs:/etc/traefik/certs:ro"
     echo "  to the proxy service's volumes in docker-compose.yml." ;;
  4) echo "Still outstanding: no certificate is configured. Traefik will serve its own"
     echo "  self-signed default. Re-run and pick 1-3 before going live." ;;
esac
if [ "$challenge" = dns ]; then cat <<DNS
DNS-01 needs credentials in the proxy container's environment. For $dns_provider:
$(case $dns_provider in
    cloudflare) echo "  CF_DNS_API_TOKEN (scope: Zone:DNS:Edit on this zone only)" ;;
    route53)    echo "  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION" ;;
    gandiv5)    echo "  GANDIV5_PERSONAL_ACCESS_TOKEN" ;;
    digitalocean) echo "  DO_AUTH_TOKEN" ;;
    hetzner)    echo "  HETZNER_API_KEY" ;;
    *) echo "  set the variables lego documents for \`$dns_provider\`" ;;
  esac)
DNS
fi

echo
echo "Next: podman-compose up -d   (then open https://$domain)"
echo "The SETUP_TOKEN in .env claims the first admin account — hand it over out of band."
