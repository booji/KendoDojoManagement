from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import IsoTimestamp, UUIDBase, UUIDType


class Attendance(UUIDBase):
    __tablename__ = "attendance"
    __table_args__ = (
        # Postgres treats NULLs as distinct, so visitor rows (member_id NULL)
        # are unconstrained; a member is checked in at most once (#431).
        UniqueConstraint(
            "session_id", "member_id", name="uq_attendance_session_member"
        ),
        CheckConstraint(
            "(member_id IS NULL) <> (visitor_name IS NULL)",
            name="ck_attendance_member_xor_visitor",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("session_instances.id"), nullable=False
    )
    # NULL for a visitor row, which has a name instead of a member. Never an
    # Account id: attendance is keyed by member however it was recorded (#340),
    # and the foreign key is what keeps it that way.
    member_id: Mapped[str | None] = mapped_column(
        UUIDType(), ForeignKey("members.id"), nullable=True
    )
    visitor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_in_at: Mapped[str] = mapped_column(IsoTimestamp(), nullable=False)
    recorded_by: Mapped[str] = mapped_column(UUIDType(), nullable=False)
