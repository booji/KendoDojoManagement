"""Auth Session rows (#455, ADR-0008) — add, find, slide, delete."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import Account, AuthSession
from app.auth.member_directory import MAY_SIGN_IN
from app.members.db_models import Member


@runtime_checkable
class AbstractAuthSessionRepository(Protocol):
    async def add(self, row: dict[str, Any]) -> None: ...

    async def find(self, token_hash: str) -> dict[str, Any] | None:
        """The row joined to its Account's role, and its Member's email and
        whether they may sign in (``may_sign_in``)."""
        ...

    async def slide(self, token_hash: str, expires_at: datetime) -> None: ...

    async def delete(self, token_hash: str) -> bool:
        """Whether a row was deleted."""
        ...

    async def delete_for_account(self, account_id: str) -> None:
        """Every row of the Account, of either kind."""
        ...

    async def delete_expired(self, now: datetime) -> None: ...


class SqlAuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, row: dict[str, Any]) -> None:
        await self._session.execute(insert(AuthSession).values(**row))

    async def find(self, token_hash: str) -> dict[str, Any] | None:
        # The email is the Member's (ADR-0006); only that column is read.
        result = await self._session.execute(
            select(
                AuthSession.account_id,
                AuthSession.kind,
                AuthSession.created_at,
                AuthSession.expires_at,
                Account.role,
                MAY_SIGN_IN.label("may_sign_in"),
                Member.email,
            )
            .join(Account, Account.id == AuthSession.account_id)
            .join(Member, Member.id == Account.member_id)
            .where(AuthSession.token_hash == token_hash)
        )
        row = result.one_or_none()
        return dict(row._mapping) if row else None

    async def slide(self, token_hash: str, expires_at: datetime) -> None:
        """Push the expiry out, and commit it.

        The slide happens in the guard, before the route runs, and most
        guarded routes are reads that never commit. Committing here is the
        only way the slide outlives the request; nothing else is pending yet.
        """
        await self._session.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash)
            .values(expires_at=expires_at)
        )
        await self._session.commit()

    async def delete(self, token_hash: str) -> bool:
        result = await self._session.execute(
            delete(AuthSession).where(AuthSession.token_hash == token_hash)
        )
        return result.rowcount > 0

    async def delete_for_account(self, account_id: str) -> None:
        await self._session.execute(
            delete(AuthSession).where(AuthSession.account_id == account_id)
        )

    async def delete_expired(self, now: datetime) -> None:
        await self._session.execute(
            delete(AuthSession).where(AuthSession.expires_at <= now)
        )
