from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.auth.models import LenientEmail
from app.core.partial_update import PartialUpdate

MembershipStatus = Literal["active", "inactive", "suspended", "archived"]


def member_name(
    display_name: str | None, first_name: str | None, surname: str | None
) -> str | None:
    """A Member's name as shown: display name, else "first surname".

    None when there is no first name either, as on an outer-joined Visitor row.
    """
    return display_name or (f"{first_name} {surname}" if first_name else None)


class CreateMemberRequest(BaseModel):
    # Normalised as sign-in normalises it: this address is the one the
    # Member signs in with, matched exactly (#432).
    email: LenientEmail
    first_name: str
    surname: str
    display_name: str | None = None
    dob: date | None = None
    join_date: date
    membership_status: MembershipStatus = "active"
    is_coach: bool = False
    is_first_aider: bool = False
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class UpdateMemberRequest(PartialUpdate):
    not_null = frozenset(
        {
            "email",
            "first_name",
            "surname",
            "join_date",
            "membership_status",
            "is_coach",
            "is_first_aider",
        }
    )

    email: LenientEmail | None = None
    first_name: str | None = None
    surname: str | None = None
    display_name: str | None = None
    dob: date | None = None
    join_date: date | None = None
    membership_status: MembershipStatus | None = None
    is_coach: bool | None = None
    is_first_aider: bool | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class SelfUpdateMemberRequest(PartialUpdate):
    """Fields a member may update on their own profile (no admin-only fields)."""

    not_null = frozenset({"first_name", "surname"})

    first_name: str | None = None
    surname: str | None = None
    display_name: str | None = None
    dob: date | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class MemberResponse(BaseModel):
    id: str
    email: str | None
    first_name: str
    surname: str
    display_name: str | None
    dob: str | None
    join_date: str
    membership_status: MembershipStatus
    is_coach: bool
    is_first_aider: bool
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    anonymised_at: str | None = None
    anonymised_by: str | None = None


class MemberListItem(MemberResponse):
    """A row of GET /members: the Member plus their current Grade's display
    name, None for a Member with no confirmed Promotion (#571)."""

    current_grade_name: str | None
