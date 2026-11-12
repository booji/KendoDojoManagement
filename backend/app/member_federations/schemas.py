from __future__ import annotations

import uuid
from datetime import date, timedelta

from pydantic import BaseModel, field_validator

from app.core.partial_update import PartialUpdate


def compute_renewal_status(renewal_date: date | str | None) -> str | None:
    """Pure function — computes renewal status from a date value.

    Returns:
      'expired'       if renewal_date < today
      'expiring_soon' if today <= renewal_date <= today + 30 days
      None            if renewal_date is None or > 30 days away
    """
    if renewal_date is None:
        return None
    if isinstance(renewal_date, str):
        renewal_date = date.fromisoformat(renewal_date)
    today = date.today()
    if renewal_date < today:
        return "expired"
    if renewal_date <= today + timedelta(days=30):
        return "expiring_soon"
    return None


class MemberFederationCreate(BaseModel):
    federation_id: uuid.UUID
    member_number: str
    renewal_date: date | None = None

    @field_validator("member_number")
    @classmethod
    def validate_member_number_length(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("member_number must be at most 100 characters")
        return v


class MemberFederationUpdate(PartialUpdate):
    not_null = frozenset({"member_number"})

    member_number: str | None = None
    renewal_date: date | None = None

    @field_validator("member_number")
    @classmethod
    def validate_member_number_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 100:
            raise ValueError("member_number must be at most 100 characters")
        return v


class MemberFederationResponse(BaseModel):
    id: str
    member_id: str
    federation_id: str
    member_number: str
    renewal_date: str | None
    renewal_status: str | None
