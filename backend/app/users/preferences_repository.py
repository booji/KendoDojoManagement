from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import User


@runtime_checkable
class AbstractUserPrefsRepo(Protocol):
    async def get_theme(self, user_id: str) -> str | None: ...

    async def set_theme(self, user_id: str, theme: str) -> str: ...


class SqlUserPrefsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_theme(self, user_id: str) -> str | None:
        row = await self._session.execute(select(User.theme).where(User.id == user_id))
        value = row.scalar_one_or_none()
        # Treat the DB default "system" as the canonical "no preference set" value
        # but return it as-is; callers decide what None means.
        return value

    async def set_theme(self, user_id: str, theme: str) -> str:
        await self._session.execute(
            update(User).where(User.id == user_id).values(theme=theme)
        )
        return theme
