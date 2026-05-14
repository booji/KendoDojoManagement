from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase, UUIDType


class Member(UUIDBase):
    __tablename__ = "members"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dob: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
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
    parental_consent_obtained: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    user_id: Mapped[str | None] = mapped_column(UUIDType(), nullable=True)
