import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./kendo.db"
)

JWT_SECRET: str = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "15"))
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

WEBAUTHN_RP_ID: str = os.getenv("WEBAUTHN_RP_ID", "localhost")
# Comma-separated list of allowed origins; Vite may use 5173 or 5174 in dev
WEBAUTHN_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "WEBAUTHN_ORIGIN",
        "http://localhost:5173,http://localhost:5174,http://localhost:8000",
    ).split(",")
    if o.strip()
]
WEBAUTHN_CHALLENGE_TTL_SECONDS: int = int(
    os.getenv("WEBAUTHN_CHALLENGE_TTL_SECONDS", "300")
)
