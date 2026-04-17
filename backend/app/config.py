import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./kendo.db")

JWT_SECRET: str = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

WEBAUTHN_RP_ID: str = os.getenv("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_ORIGIN: str = os.getenv("WEBAUTHN_ORIGIN", "http://localhost:5173")
WEBAUTHN_CHALLENGE_TTL_SECONDS: int = int(
    os.getenv("WEBAUTHN_CHALLENGE_TTL_SECONDS", "300")
)
