from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class User(UUIDBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    theme: Mapped[str] = mapped_column(String(10), nullable=False, default="system")
    pending_challenge: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    challenge_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class PasskeyCredential(UUIDBase):
    __tablename__ = "passkey_credentials"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, unique=True
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
