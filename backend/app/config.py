import os

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./kendo.db"
)

JWT_SECRET: str = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "15"))
