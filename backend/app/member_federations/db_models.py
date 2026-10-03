from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase, UUIDType


class MemberFederation(UUIDBase):
    __tablename__ = "member_federations"
    __table_args__ = (
        UniqueConstraint(
            "member_id", "federation_id", name="uq_member_federations_member_federation"
        ),
    )

    member_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("members.id"), nullable=False
    )
    federation_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("federations.id"), nullable=False
    )
    member_number: Mapped[str] = mapped_column(String(100), nullable=False)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
