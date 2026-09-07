"""Resolve the originating client IP, optionally trusting a reverse proxy.

In UAT/PROD the app runs behind Traefik, so ``request.client.host`` is always
the proxy's address. When ``TRUST_PROXY_XFF`` is enabled we instead read the
client IP from ``X-Forwarded-For`` (leftmost entry = original client). The flag
defaults to off, and is only safe to turn on where every request arrives through
a proxy that overwrites the header: the dev stack enables it because Traefik
fronts it (#374), but the direct :8000 escape hatch there can still forge it,
and the test stack has no proxy at all.
"""

from fastapi import Request

from app import config


def client_ip(request: Request) -> str:
    """Return the originating client IP for rate limiting and lockout keys."""
    peer = request.client.host if request.client else "unknown"
    if config.TRUST_PROXY_XFF:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return peer
