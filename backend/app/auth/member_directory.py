"""Narrow port auth uses to ask questions about Members.

Every Account belongs to exactly one Member (#432, ADR-0006), so creating an
Account starts from a Member id. Auth needs exactly two things here:
1. The id of the admin-created Member with this email, if any (the
   registration gate, #239).
2. The id of the Member for an invited or first-admin email, creating that
   Member if there is none yet.

Everything else about Member stays inside app.members — this module hides
that repository behind the two questions auth actually asks, per the
deep-modules convention in CLAUDE.md.
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
    async def member_id_for(self, email: str) -> str | None: ...

    async def ensure_member(
        self, email: str, first_name: str, surname: str, *, claim: bool = False
    ) -> str: ...


class SqlMemberDirectory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def member_id_for(self, email: str) -> str | None:
        # The id alone: this answers unauthenticated callers, so the Member
        # row itself -- date of birth, safeguarding fields -- is never loaded
        # on their behalf (ADR-0006).
        result = await self._session.execute(
            select(Member.id).where(Member.email == email)
        )
        return result.scalar_one_or_none()

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
        member_id = await self.member_id_for(email)
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
