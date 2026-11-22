"""Invite repository — mint, look up, list, revoke, redeem (#257).

Mirrors the shape of app.auth.recovery_repository: a narrow Abstract*
Protocol plus a Sql* implementation operating on plain dicts, so routers and
service functions never see the ORM model directly.
"""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import Invite


def _to_dict(obj: Invite) -> dict[str, Any]:
    return {
        "id": obj.id,
        "email": obj.email,
        "first_name": obj.first_name,
        "surname": obj.surname,
        "token_hash": obj.token_hash,
        "expires_at": obj.expires_at,
        "issued_by": obj.issued_by,
        "redeemed_at": obj.redeemed_at,
        "revoked_at": obj.revoked_at,
        "created_at": obj.created_at,
    }


@runtime_checkable
class AbstractInviteRepository(Protocol):
    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, invite_id: str) -> dict[str, Any] | None: ...

    async def get_by_token_hash(self, token_hash: str) -> dict[str, Any] | None: ...

    async def list(self) -> builtins.list[dict[str, Any]]: ...

    async def mark_revoked(self, invite_id: str) -> dict[str, Any] | None: ...

    async def mark_redeemed(self, invite_id: str) -> dict[str, Any] | None: ...


class SqlInviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        obj = Invite(**data)
        self._session.add(obj)
        await self._session.flush()
        return _to_dict(obj)

    async def get(self, invite_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Invite).where(Invite.id == invite_id)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def get_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Invite).where(Invite.token_hash == token_hash)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def list(self) -> builtins.list[dict[str, Any]]:
        result = await self._session.execute(select(Invite))
        return [_to_dict(obj) for obj in result.scalars().all()]

    async def mark_revoked(self, invite_id: str) -> dict[str, Any] | None:
        await self._session.execute(
            update(Invite)
            .where(Invite.id == invite_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.flush()
        return await self.get(invite_id)

    async def mark_redeemed(self, invite_id: str) -> dict[str, Any] | None:
        """Claim an invite for redemption, or report that someone else already did.

        The `redeemed_at IS NULL` guard is what actually enforces single use: a
        caller that checked usability by reading the row first is racing anyone
        else who read it in the same window, and only the write can settle that.
        Returning None means this caller lost and must be refused.
        """
        result = await self._session.execute(
            update(Invite)
            .where(Invite.id == invite_id, Invite.redeemed_at.is_(None))
            .values(redeemed_at=datetime.now(UTC))
        )
        await self._session.flush()
        # UPDATE yields a CursorResult at runtime; execute()'s stubs say Result.
        if result.rowcount == 0:  # ty: ignore[missing-attribute]
            return None
        return await self.get(invite_id)
