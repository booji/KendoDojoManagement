from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class Attendance(UUIDBase):
    __tablename__ = "attendance"

    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    member_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    visitor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_in_at: Mapped[str] = mapped_column(String(50), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)


class CheckinToken(UUIDBase):
    __tablename__ = "checkin_tokens"

    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    token_lookup: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(50), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
