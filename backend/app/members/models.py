from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

MembershipStatus = Literal["active", "inactive", "suspended", "archived"]


class CreateMemberRequest(BaseModel):
    email: str
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


class UpdateMemberRequest(BaseModel):
    email: str | None = None
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


class SelfUpdateMemberRequest(BaseModel):
    """Fields a member may update on their own profile (no admin-only fields)."""

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
