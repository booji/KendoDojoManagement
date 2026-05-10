from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

MembershipStatus = Literal["active", "inactive", "suspended"]


class CreateMemberRequest(BaseModel):
    email: str
    full_name: str
    dob: date
    join_date: date
    membership_status: MembershipStatus = "active"
    is_coach: bool = False
    is_first_aider: bool = False
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    parental_consent_obtained: bool = False


class UpdateMemberRequest(BaseModel):
    email: str | None = None
    full_name: str | None = None
    dob: date | None = None
    join_date: date | None = None
    membership_status: MembershipStatus | None = None
    is_coach: bool | None = None
    is_first_aider: bool | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    parental_consent_obtained: bool | None = None


class SelfUpdateMemberRequest(BaseModel):
    """Fields a member may update on their own profile (no admin-only fields)."""

    full_name: str | None = None
    dob: date | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class MemberResponse(BaseModel):
    id: str
    email: str
    full_name: str
    join_date: str
    membership_status: MembershipStatus
    is_coach: bool
    is_first_aider: bool
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    parental_consent_obtained: bool
    is_minor: bool
