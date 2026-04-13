"""Passkey credential repository — list, get, update, delete."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import PasskeyCredential


def _to_dict(obj: PasskeyCredential) -> dict[str, Any]:
    return {
        "id": obj.id,
        "user_id": obj.user_id,
        "credential_id": obj.credential_id,
        "public_key": obj.public_key,
        "sign_count": obj.sign_count,
        "label": obj.label,
        "aaguid": obj.aaguid,
        "created_at": obj.created_at,
        "last_used_at": obj.last_used_at,
    }


@runtime_checkable
class AbstractPasskeyRepository(Protocol):
    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]: ...

    async def get(self, passkey_id: str) -> dict[str, Any] | None: ...

    async def update_label(
        self, passkey_id: str, user_id: str, label: str
    ) -> dict[str, Any] | None: ...

    async def delete(self, passkey_id: str, user_id: str) -> bool: ...

    async def count_for_user(self, user_id: str) -> int: ...


class SqlPasskeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(PasskeyCredential).where(PasskeyCredential.user_id == user_id)
        )
        return [_to_dict(obj) for obj in result.scalars().all()]

    async def get(self, passkey_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(PasskeyCredential).where(PasskeyCredential.id == passkey_id)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def update_label(
        self, passkey_id: str, user_id: str, label: str
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(PasskeyCredential).where(
                PasskeyCredential.id == passkey_id,
                PasskeyCredential.user_id == user_id,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.label = label
        await self._session.flush()
        return _to_dict(obj)

    async def delete(self, passkey_id: str, user_id: str) -> bool:
        result = await self._session.execute(
            select(PasskeyCredential).where(
                PasskeyCredential.id == passkey_id,
                PasskeyCredential.user_id == user_id,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return False
        await self._session.delete(obj)
        await self._session.flush()
        return True

    async def count_for_user(self, user_id: str) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(PasskeyCredential).where(
                PasskeyCredential.user_id == user_id
            )
        )
        return result.scalar_one()
