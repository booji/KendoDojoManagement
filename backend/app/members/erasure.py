"""GDPR erasure planning — pure functions, no I/O.

Builds the anonymisation plan for a member and decides whether an erasure
request is permitted. Both functions are pure: no database access, no HTTP,
no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_RELATED_RECORDS_TO_DELETE: frozenset[str] = frozenset(
    {
        "user",
        "passkey_credentials",
        "recovery_codes",
        "recovery_attempts",
        "admin_recovery_tokens",
        "grade_history",
        "member_federations",
    }
)


@dataclass(frozen=True)
class ErasurePlan:
    scrub: dict[str, Any]
    delete: frozenset[str] = field(default_factory=lambda: _RELATED_RECORDS_TO_DELETE)


@dataclass(frozen=True)
class ErasureDecision:
    allowed: bool
    reason: str | None = None


def build_erasure_plan() -> ErasurePlan:
    """Return the anonymisation plan applied to any erased member.

    The plan is the same for every member — it overwrites PII with fixed
    placeholders rather than deriving anything from the current values — so it
    takes no arguments. `id` is deliberately absent: erasure anonymises the row
    in place and must not orphan attendance history.
    """
    scrub = {
        "first_name": "Deleted",
        "surname": "member",
        "email": None,
        "display_name": None,
        "dob": None,
        "emergency_contact_name": None,
        "emergency_contact_phone": None,
    }
    return ErasurePlan(scrub=scrub, delete=_RELATED_RECORDS_TO_DELETE)


def can_erase(
    actor_user_id: str,
    member: dict[str, Any],
    is_admin: bool,
    admin_count: int,
) -> ErasureDecision:
    """Decide whether `member` may be erased by `actor_user_id`."""
    if member.get("membership_status") != "archived":
        return ErasureDecision(
            allowed=False,
            reason="Member must be archived before erasure",
        )
    if member.get("user_id") == actor_user_id:
        return ErasureDecision(
            allowed=False,
            reason="You cannot erase yourself",
        )
    if is_admin and admin_count <= 1:
        return ErasureDecision(
            allowed=False,
            reason="Cannot erase the last admin",
        )
    return ErasureDecision(allowed=True, reason=None)
