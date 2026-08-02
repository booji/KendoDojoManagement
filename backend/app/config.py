import logging
import os

from dotenv import load_dotenv

load_dotenv(override=False)

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./kendo.db")

JWT_SECRET: str = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

# Trust X-Forwarded-For for client IP (rate limiting, lockout). Enable ONLY when
# the app is reachable solely through a trusted reverse proxy (Traefik in
# UAT/PROD) that overwrites the header; leaving it off keeps dev spoof-proof.
TRUST_PROXY_XFF: bool = os.getenv("TRUST_PROXY_XFF", "false").lower() == "true"

# IANA timezone the dojo runs in. Sourced from the container's TZ env var so the
# calendar feed anchors event wall-clock times to the dojo's zone (with correct
# DST) instead of emitting floating time. Defaults to UTC.
TIMEZONE: str = os.getenv("TZ", "UTC")

# Minimum wall-clock duration (ms) the passkey begin endpoints must take,
# regardless of whether the email is known/authorized (real path) or
# unknown/unauthorized (decoy path). Closes a timing side channel: the real
# path does strictly more DB work (credential SELECT, pending_challenge
# UPDATE, commit) than the decoy path, which otherwise lets an attacker
# enumerate registered emails from response latency alone. This value MUST
# stay above the real path's p99 latency, or the floor stops masking the
# asymmetry it exists to hide.
# A non-positive value would make the pad never fire and silently restore the
# leak, so a typo or a well-meaning "disable this in dev" is treated as
# misconfiguration rather than honoured. Same for a non-integer.
_AUTH_BEGIN_MIN_DURATION_DEFAULT = 50
try:
    AUTH_BEGIN_MIN_DURATION_MS: int = int(
        os.getenv("AUTH_BEGIN_MIN_DURATION_MS", str(_AUTH_BEGIN_MIN_DURATION_DEFAULT))
    )
except ValueError:
    AUTH_BEGIN_MIN_DURATION_MS = _AUTH_BEGIN_MIN_DURATION_DEFAULT
    logging.getLogger(__name__).warning(
        "AUTH_BEGIN_MIN_DURATION_MS is not an integer; falling back to %dms",
        _AUTH_BEGIN_MIN_DURATION_DEFAULT,
    )
if AUTH_BEGIN_MIN_DURATION_MS <= 0:
    logging.getLogger(__name__).warning(
        "AUTH_BEGIN_MIN_DURATION_MS must be positive; falling back to %dms. "
        "A non-positive floor disables timing-side-channel protection on the "
        "passkey begin endpoints.",
        _AUTH_BEGIN_MIN_DURATION_DEFAULT,
    )
    AUTH_BEGIN_MIN_DURATION_MS = _AUTH_BEGIN_MIN_DURATION_DEFAULT

WEBAUTHN_RP_ID: str = os.getenv("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_ORIGIN: str = os.getenv("WEBAUTHN_ORIGIN", "http://localhost:5173")
WEBAUTHN_CHALLENGE_TTL_SECONDS: int = int(
    os.getenv("WEBAUTHN_CHALLENGE_TTL_SECONDS", "300")
)

_cors_origins_env: str = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else [WEBAUTHN_ORIGIN]
)
