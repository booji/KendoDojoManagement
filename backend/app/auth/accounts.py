"""Finding an Account by the address it signs in with (#432, ADR-0006).

The email lives once, on the Member. Every lookup here joins the Member for
that one column and loads only the Account row: pre-authentication code must
never pull a Member into memory, with its date of birth and safeguarding
fields, on behalf of someone who has not yet proved who they are.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import User
from app.members.db_models import Member


async def account_for_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User)
        .join(Member, Member.id == User.member_id)
        .where(Member.email == email)
    )
    return result.scalar_one_or_none()


async def account_for_member(session: AsyncSession, member_id: str) -> User | None:
    result = await session.execute(select(User).where(User.member_id == member_id))
    return result.scalar_one_or_none()


async def sign_in_email(session: AsyncSession, user_id: str) -> str | None:
    """The address the Account signs in with: its Member's, as of now."""
    result = await session.execute(
        select(Member.email)
        .join(User, User.member_id == Member.id)
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()
