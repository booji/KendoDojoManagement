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
