from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase, UUIDType


class Member(UUIDBase):
    __tablename__ = "members"

    # Nullable to allow GDPR erasure to scrub email to NULL while keeping the
    # unique constraint (Postgres treats multiple NULLs as distinct).
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    surname: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dob: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "YYYY-MM-DD"
    join_date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    membership_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    is_coach: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_first_aider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_contact_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(UUIDType(), nullable=True)
    anonymised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    anonymised_by: Mapped[str | None] = mapped_column(UUIDType(), nullable=True)
