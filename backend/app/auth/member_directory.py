"""Narrow port auth uses to ask questions about Members.

Every Account belongs to exactly one Member (#432, ADR-0006), so creating an
Account starts from a Member id. Auth asks the members domain two things,
and both are here:
1. The id of the Member for an invited or first-admin email, creating that
   Member if there is none yet.
2. Whether a Member may sign in (#484). The members domain owns that rule;
   auth gets it as `barred_status` for one email, or as `MAY_SIGN_IN`, the
   same rule as a SQL predicate on `members`, for a query that must read it
   in the statement that joins the Member (the Auth Session join, ADR-0008).

This module hides the Member repository behind them, per the deep-modules
convention in CLAUDE.md. Elsewhere auth reads only the Member's email, as a
single column in SQL, so a lookup never loads the Member row itself
(ADR-0006).
"""

from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.unit_of_work import AbstractUnitOfWork
from app.members.db_models import BARRED_FROM_SIGN_IN, MAY_SIGN_IN, Member
from app.members.models import MembershipStatus
from app.members.repository import SqlMemberRepository

__all__ = [
    "MAY_SIGN_IN",
    "MemberDirectory",
    "SqlMemberDirectory",
    "member_directory_for",
]


@runtime_checkable
class MemberDirectory(Protocol):
    async def ensure_member(
        self, email: str, first_name: str, surname: str, *, claim: bool = False
    ) -> str: ...

    async def barred_status(self, email: str) -> MembershipStatus | None: ...


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

    async def barred_status(self, email: str) -> MembershipStatus | None:
        """The Membership Status that bars the Member for `email` from signing
        in, or None if they may, or if no Member has that email."""
        status = (
            await self._session.execute(
                select(Member.membership_status).where(Member.email == email)
            )
        ).scalar_one_or_none()
        return status if status in BARRED_FROM_SIGN_IN else None  # type: ignore[return-value]


def member_directory_for(uow: AbstractUnitOfWork) -> MemberDirectory:
    return SqlMemberDirectory(uow.session)
