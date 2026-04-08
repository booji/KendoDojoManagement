from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class Attendance(UUIDBase):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("session_id", "member_id"),)

    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    member_id: Mapped[str] = mapped_column(String(36), nullable=False)
    checked_in_at: Mapped[str] = mapped_column(String(50), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)


class CheckinToken(UUIDBase):
    __tablename__ = "checkin_tokens"

    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(50), nullable=False)
