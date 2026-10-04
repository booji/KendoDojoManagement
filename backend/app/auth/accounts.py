"""Finding an Account by the address it signs in with (#432, ADR-0006).

The email lives once, on the Member. Every lookup here joins the Member for
that one column and loads only the Account row: pre-authentication code must
never pull a Member into memory, with its date of birth and safeguarding
fields, on behalf of someone who has not yet proved who they are.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import Account
from app.members.db_models import Member


async def account_for_email(session: AsyncSession, email: str) -> Account | None:
    result = await session.execute(
        select(Account)
        .join(Member, Member.id == Account.member_id)
        .where(Member.email == email)
    )
    return result.scalar_one_or_none()


async def account_for_member(session: AsyncSession, member_id: str) -> Account | None:
    result = await session.execute(
        select(Account).where(Account.member_id == member_id)
    )
    return result.scalar_one_or_none()


async def sign_in_email(session: AsyncSession, user_id: str) -> str | None:
    """The address the Account signs in with: its Member's, as of now."""
    result = await session.execute(
        select(Member.email)
        .join(Account, Account.member_id == Member.id)
        .where(Account.id == user_id)
    )
    return result.scalar_one_or_none()
