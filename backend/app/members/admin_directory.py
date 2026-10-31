"""Small read-only lookup over the auth accounts table, used by member erasure
to decide whether a target member is an admin and how many admins who can
still sign in remain. Kept separate from AbstractMemberRepository since it queries a
different aggregate (accounts, not members).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.accounts import MAY_SIGN_IN
from app.auth.db_models import Account
from app.members.db_models import Member


@runtime_checkable
class AbstractAdminDirectory(Protocol):
    async def is_admin(self, user_id: str | None) -> bool: ...

    async def count_admins(self) -> int: ...


class SqlAdminDirectory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_admin(self, user_id: str | None) -> bool:
        if user_id is None:
            return False
        # Mirror count_admins: only an admin who may sign in counts (#484),
        # so the last-admin guard and the count it compares against share
        # semantics.
        result = await self._session.execute(
            select(Account.role)
            .join(Member, Member.id == Account.member_id)
            .where(Account.id == user_id, MAY_SIGN_IN)
        )
        role = result.scalar_one_or_none()
        return role == "admin"

    async def count_admins(self) -> int:
        # Row-level lock (FOR UPDATE) on the admin set so concurrent
        # erasures serialise: two admins erasing each other's linked member at
        # once must not both observe the pre-delete count and drop the dojo to
        # zero admins. FOR UPDATE cannot combine with an aggregate, so we lock
        # the rows and count them in Python.
        result = await self._session.execute(
            select(Account.id)
            .join(Member, Member.id == Account.member_id)
            .where(Account.role == "admin", MAY_SIGN_IN)
            .with_for_update(of=Account)
        )
        return len(result.scalars().all())
