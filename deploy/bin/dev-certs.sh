#!/usr/bin/env bash
# The dev TLS certificate for https://dojo.localhost:8443, behind `make certs`.
#
# Since #374 the dev stack is HTTPS-only for anything authenticated: .env.dev
# sets COOKIE_SECURE=true and browsers refuse WebAuthn on a page with a
# certificate error, so a *degraded* certificate looks like a working stack
# until the first login. Hence two rules (#379):
#
#   - say which generator ran and whether the result is trusted, and
#   - repair itself: a self-signed pair is reissued as soon as mkcert appears,
#     and a pair that no longer covers the dev host is reissued too.
#
# Installing the CA into the browser's trust store is deliberately NOT done
# here — the browser may be on another OS entirely (WSL2, a VM, a remote box)
# and this script cannot know. docs/contributing/dev-stack.md carries that table.
set -euo pipefail

host="${CERT_HOST:-dojo.localhost}"
dir="${CERT_DIR:-deploy/certs}"
cert="$dir/$host.pem"
key="$dir/$host-key.pem"
force=false
[ "${1:-}" = "--force" ] && force=true

have() { command -v "$1" >/dev/null 2>&1; }

# Inspection needs openssl. Without it the only reissue triggers are a missing
# half and --force: guessing from an uninspectable file would be worse than
# leaving it, since a working pair reissued as self-signed is a regression.
issued_by_mkcert() { openssl x509 -in "$cert" -noout -issuer 2>/dev/null | grep -qi mkcert; }
covers_host() {
  openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null |
    grep -qF "DNS:$host"
}

existed=false
[ -f "$cert" ] && [ -f "$key" ] && existed=true

reason=""
if [ "$force" = true ]; then
  reason="--force"
elif [ "$existed" = false ]; then
  reason="no certificate for $host"
elif have openssl; then
  if ! covers_host; then
    reason="the existing certificate does not cover $host"
  elif have mkcert && ! issued_by_mkcert; then
    reason="the existing certificate is self-signed and mkcert is now available"
  fi
fi

if [ -z "$reason" ]; then
  if have openssl && issued_by_mkcert; then
    echo "certs: $cert is issued by your mkcert CA — nothing to do."
  else
    echo "certs: $cert is SELF-SIGNED. Browsers will warn, and passkey ceremonies"
    echo "       will fail on https://$host:8443. Install mkcert and re-run"
    echo "       \`make certs\` — it will reissue. See docs/contributing/dev-stack.md."
  fi
  exit 0
fi

mkdir -p "$dir"
if have mkcert; then
  mkcert -cert-file "$cert" -key-file "$key" "$host" localhost 127.0.0.1 ::1
  echo "certs: issued $cert with mkcert ($reason)."
  echo "       Trusted only where your mkcert CA is installed. If your browser runs"
  echo "       on a different OS than this stack (WSL2, a VM, a remote box), install"
  echo "       the CA there too — see docs/contributing/dev-stack.md."
elif have openssl; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -subj "/CN=$host" \
    -addext "subjectAltName=DNS:$host,DNS:localhost,IP:127.0.0.1" \
    -keyout "$key" -out "$cert" 2>/dev/null
  echo "certs: issued $cert with openssl — SELF-SIGNED and untrusted ($reason)."
  echo "       Browsers will warn and passkey ceremonies will fail. Install mkcert,"
  echo "       run \`mkcert -install\`, then \`make certs\` again to reissue."
else
  echo "certs: neither mkcert nor openssl on PATH — cannot generate the dev certificate." >&2
  echo "       The dev stack serves https://$host:8443 and .env.dev sets COOKIE_SECURE=true," >&2
  echo "       so without TLS there is no origin that can hold a session." >&2
  exit 1
fi
chmod 600 "$key"

if [ "$existed" = true ]; then
  # Traefik's file provider watches the config files, not the certificate bytes,
  # so a replaced pair is not picked up until the proxy restarts — which looks
  # exactly like the new certificate not having worked.
  echo "       Traefik loads the certificate at startup: restart the proxy for this"
  echo "       one to take effect (\`make down && make dev\`)."
fi
