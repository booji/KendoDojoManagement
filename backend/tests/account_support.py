"""Seeding an Account for DB-backed tests (#432).

Every Account belongs to exactly one Member, and the email it signs in with
is the Member's. A test that needs "a user with this email" therefore needs
both rows; this inserts them, reusing a Member the test already seeded for
that email.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import User
from app.members.db_models import Member


async def seed_member(session: AsyncSession, email: str | None, **fields: Any) -> str:
    """The id of the Member with `email`, inserting one if there is none."""
    if email is not None:
        existing = await session.execute(select(Member.id).where(Member.email == email))
        member_id = existing.scalar_one_or_none()
        if member_id is not None:
            return member_id
    member_id = str(uuid.uuid4())
    await session.execute(
        insert(Member).values(
            id=member_id,
            email=email,
            first_name=fields.pop("first_name", "Test"),
            surname=fields.pop("surname", "User"),
            join_date=fields.pop("join_date", "2026-01-01"),
            membership_status=fields.pop("membership_status", "active"),
            is_coach=fields.pop("is_coach", False),
            is_first_aider=fields.pop("is_first_aider", False),
            **fields,
        )
    )
    return member_id


async def seed_account(
    session: AsyncSession,
    email: str,
    *,
    user_id: str | None = None,
    role: str = "member",
    is_active: bool = True,
    **user_values: Any,
) -> str:
    """Insert a Member (unless one has `email`) and its Account; the Account id."""
    member_id = await seed_member(session, email)
    user_id = user_id or str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=user_id,
            member_id=member_id,
            role=role,
            is_active=is_active,
            **user_values,
        )
    )
    return user_id
