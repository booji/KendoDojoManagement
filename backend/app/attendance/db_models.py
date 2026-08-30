from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase, UUIDType


class Attendance(UUIDBase):
    __tablename__ = "attendance"

    session_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("session_instances.id"), nullable=False
    )
    # NULL for a visitor row, which has a name instead of a member. Never a
    # User id: attendance is keyed by member however it was recorded (#340),
    # and the foreign key is what keeps it that way.
    member_id: Mapped[str | None] = mapped_column(
        UUIDType(), ForeignKey("members.id"), nullable=True
    )
    visitor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_in_at: Mapped[str] = mapped_column(String(50), nullable=False)
    recorded_by: Mapped[str] = mapped_column(UUIDType(), nullable=False)


class CheckinToken(UUIDBase):
    __tablename__ = "checkin_tokens"

    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    token_lookup: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("session_instances.id"), nullable=False
    )
    expires_at: Mapped[str] = mapped_column(String(50), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
