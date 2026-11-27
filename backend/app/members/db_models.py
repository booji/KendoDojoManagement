from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import IsoDate, UUIDBase, UUIDType
from app.members.schemas import MembershipStatus

# Who may sign in, and keep using an Auth Session they already hold (#484):
# a Member whose Membership Status is neither of these. `inactive` keeps
# access. Auth reads it only through app.auth.member_directory.
BARRED_FROM_SIGN_IN: tuple[MembershipStatus, ...] = ("archived", "suspended")


class Member(UUIDBase):
    __tablename__ = "members"
    # Lookups match exactly against LenientEmail's lowercase form (#592).
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_members_email_lowercase"),
    )

    # Nullable to allow GDPR erasure to scrub email to NULL while keeping the
    # unique constraint (Postgres treats multiple NULLs as distinct).
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    surname: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dob: Mapped[str | None] = mapped_column(IsoDate(), nullable=True)
    join_date: Mapped[str] = mapped_column(IsoDate(), nullable=False)
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
    anonymised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    anonymised_by: Mapped[str | None] = mapped_column(UUIDType(), nullable=True)
    # Set when the first-admin claim created this Member at begin, cleared
    # when that claim completes. Any still set then belong to abandoned claim
    # attempts and are removed (#446). A Member already on the roster is never
    # marked, so a claim can never remove one.
    claim_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# The same rule as one SQL predicate on `members`, so a query can read it in
# the statement that joins the Member (the Auth Session join, ADR-0008).
MAY_SIGN_IN = Member.membership_status.not_in(BARRED_FROM_SIGN_IN)
