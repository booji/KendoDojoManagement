from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase, UUIDType


class GradeHistory(UUIDBase):
    __tablename__ = "grade_history"

    member_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("members.id"), nullable=False, index=True
    )
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    promoted_at: Mapped[str] = mapped_column(String(50), nullable=False)
    assigned_by: Mapped[str] = mapped_column(UUIDType(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="confirmed"
    )
