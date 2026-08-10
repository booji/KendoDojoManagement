import logging
import os

from dotenv import load_dotenv

load_dotenv(override=False)

DATABASE_URL: str = os.getenv("DATABASE_URL") or ""

# development | production. Explicit and never inferred from other settings
# (e.g. COOKIE_SECURE) — production-only checks below key off this alone.
APP_ENV: str = os.getenv("APP_ENV", "development")

JWT_SECRET: str = os.getenv("JWT_SECRET") or ""
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
#
# 100ms is calibrated, not guessed (#268): measured against PostgreSQL, the
# real path's p99 is 16.8ms and its worst observed case 27.9ms with requests
# arriving one at a time. The headroom over that is deliberate — the
# measurement is from a developer workstation, and the commit that dominates
# the real path is slower on production storage. Full method, numbers and the
# reasoning for this figure: docs/auth-timing-calibration.md.
#
# Raising this further is not the fix for a *saturated* server: past ~4
# simultaneous begin requests, queueing alone puts the p99 beyond any sane
# floor. ConstantTimeAuthMiddleware logs a warning on every overrun; treat that
# as a capacity or rate-limit signal.
#
# A non-positive value would make the pad never fire and silently restore the
# leak, so a typo or a well-meaning "disable this in dev" is treated as
# misconfiguration rather than honoured. Same for a non-integer.
_AUTH_BEGIN_MIN_DURATION_DEFAULT = 100
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

# Names of module-level globals in this file that MUST hold a non-blank
# string at startup. A misconfigured deployment (unset/empty/whitespace-only)
# must fail fast here rather than boot cleanly and fail later at first use
# (e.g. JWT_SECRET only used to raise on first encode_token() call). Add
# future required secrets to this tuple — validate_startup_config() reads
# each by name from this module's globals at call time, so no other wiring
# is needed.
_REQUIRED_STARTUP_VARS: tuple[str, ...] = ("JWT_SECRET", "DATABASE_URL")

# WEBAUTHN_RP_ID / WEBAUTHN_ORIGIN defaults that are only safe for local dev.
# Left at these values in production, passkeys silently bind to "localhost"
# instead of the real domain — checked below only when APP_ENV=="production"
# so developers running with the stock .env are never nagged.
_WEBAUTHN_RP_ID_DEV_DEFAULT = "localhost"
_WEBAUTHN_ORIGIN_DEV_DEFAULT = "http://localhost:5173"


def validate_startup_config() -> None:
    """Raise RuntimeError naming the offending variable if any required
    startup config is unset, empty, or whitespace-only, or if a
    production-shaped deployment (APP_ENV=="production") is still carrying
    dev-only WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN defaults.

    Reads each variable from this module's globals at call time (not at
    import time), so tests can monkeypatch e.g. `config.JWT_SECRET` and
    callers (app.main.lifespan) can invoke this with no arguments before any
    DB or network I/O.
    """
    for name in _REQUIRED_STARTUP_VARS:
        value = globals().get(name)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(
                f"{name} environment variable must be set to a non-empty "
                "value. Refusing to start with a missing/blank secret."
            )

    if globals().get("APP_ENV") == "production":
        if globals().get("WEBAUTHN_RP_ID") == _WEBAUTHN_RP_ID_DEV_DEFAULT:
            raise RuntimeError(
                "WEBAUTHN_RP_ID is still set to the localhost dev default "
                "while APP_ENV=production. Set it to the dojo's real domain."
            )
        if globals().get("WEBAUTHN_ORIGIN") == _WEBAUTHN_ORIGIN_DEV_DEFAULT:
            raise RuntimeError(
                "WEBAUTHN_ORIGIN is still set to the localhost dev default "
                "while APP_ENV=production. Set it to the dojo's real origin."
            )
