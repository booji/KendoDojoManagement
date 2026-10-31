"""Narrow port auth uses to ask questions about Members.

Every Account belongs to exactly one Member (#432, ADR-0006), so creating an
Account starts from a Member id. The one thing auth needs from the Member
repository is here: the id of the Member for an invited or first-admin email,
creating that Member if there is none yet. This module hides that repository
behind it, per the deep-modules convention in CLAUDE.md.

It is not the only place auth touches Members. app.auth.accounts and invite
minting read single columns of `members` in SQL -- the email, and the
Membership Status that decides sign-in (MAY_SIGN_IN, #484) -- so a lookup never
loads the Member row itself (ADR-0006).
"""

from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.unit_of_work import AbstractUnitOfWork
from app.members.db_models import Member
from app.members.repository import SqlMemberRepository


@runtime_checkable
class MemberDirectory(Protocol):
    async def ensure_member(
        self, email: str, first_name: str, surname: str, *, claim: bool = False
    ) -> str: ...


class SqlMemberDirectory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_member(
        self, email: str, first_name: str, surname: str, *, claim: bool = False
    ) -> str:
        """The Member for `email`, created with this name if there is none (#257).

        An explicit invite, or the first-admin claim, may name an email no
        Member has yet. An existing Member keeps whatever name it already
        has -- the register is the authority on someone already in it, not
        an invite raised later.

        `claim` marks a Member this creates as a claim attempt's, so an
        abandoned attempt can be told from the roster and removed (#446).
        """
        # The id alone: invite redemption answers unauthenticated callers, so
        # the Member row itself -- date of birth, safeguarding fields -- is
        # never loaded on their behalf (ADR-0006).
        member_id = (
            await self._session.execute(select(Member.id).where(Member.email == email))
        ).scalar_one_or_none()
        if member_id is None:
            member = await SqlMemberRepository(self._session).add(
                {
                    "email": email,
                    "first_name": first_name,
                    "surname": surname,
                    "join_date": date.today().isoformat(),
                    **({"claim_attempted_at": datetime.now(UTC)} if claim else {}),
                }
            )
            member_id = member["id"]
        return member_id


def member_directory_for(uow: AbstractUnitOfWork) -> MemberDirectory:
    return SqlMemberDirectory(uow.session)
