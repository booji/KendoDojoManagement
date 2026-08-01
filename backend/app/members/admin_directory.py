"""Small read-only lookup over the auth users table, used by member erasure
to decide whether a target member is an admin and how many active admins
remain. Kept separate from AbstractMemberRepository since it queries a
different aggregate (users, not members).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import User


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
        # Mirror count_admins: only an *active* admin counts, so the
        # last-admin guard and the count it compares against share semantics.
        result = await self._session.execute(
            select(User.role).where(User.id == user_id, User.is_active.is_(True))
        )
        role = result.scalar_one_or_none()
        return role == "admin"

    async def count_admins(self) -> int:
        # Row-level lock (FOR UPDATE) on the active-admin set so concurrent
        # erasures serialise: two admins erasing each other's linked member at
        # once must not both observe the pre-delete count and drop the dojo to
        # zero admins. FOR UPDATE cannot combine with an aggregate, so we lock
        # the rows and count them in Python. No-op lock on SQLite (dev).
        result = await self._session.execute(
            select(User.id)
            .where(User.role == "admin", User.is_active.is_(True))
            .with_for_update()
        )
        return len(result.scalars().all())
