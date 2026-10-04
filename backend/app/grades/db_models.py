from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import IsoTimestamp, UUIDBase, UUIDType


class GradeHistory(UUIDBase):
    __tablename__ = "grade_history"

    member_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("members.id"), nullable=False, index=True
    )
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    # Derivable from `grade` today, kept on purpose: it records what was
    # displayed at the time of the Promotion, which is the point of an audit
    # table (#418, #435).
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    promoted_at: Mapped[str] = mapped_column(IsoTimestamp(), nullable=False)
    assigned_by: Mapped[str | None] = mapped_column(UUIDType(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="confirmed"
    )
