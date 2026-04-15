"""Recovery code repository — create, query, invalidate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import RecoveryCode


def _to_dict(obj: RecoveryCode) -> dict[str, Any]:
    # code_hash intentionally excluded — never returned to callers
    return {
        "id": obj.id,
        "user_id": obj.user_id,
        "set_id": obj.set_id,
        "used_at": obj.used_at,
        "created_at": obj.created_at,
    }


@runtime_checkable
class AbstractRecoveryRepository(Protocol):
    async def create_codes(
        self, user_id: str, hashed_codes: list[str], set_id: str
    ) -> list[dict[str, Any]]: ...

    async def has_active_set(self, user_id: str) -> bool: ...

    async def invalidate_all(self, user_id: str) -> None: ...

    async def count_unused(self, user_id: str) -> int: ...

    async def get_all_for_user(self, user_id: str) -> list[dict[str, Any]]: ...


class SqlRecoveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_codes(
        self, user_id: str, hashed_codes: list[str], set_id: str
    ) -> list[dict[str, Any]]:
        records = []
        for h in hashed_codes:
            obj = RecoveryCode(
                user_id=user_id,
                code_hash=h,
                set_id=set_id,
            )
            self._session.add(obj)
            records.append(obj)
        await self._session.flush()
        return [_to_dict(r) for r in records]

    async def has_active_set(self, user_id: str) -> bool:
        result = await self._session.execute(
            select(func.count())
            .select_from(RecoveryCode)
            .where(
                RecoveryCode.user_id == user_id,
                RecoveryCode.used_at.is_(None),
            )
        )
        return result.scalar_one() > 0

    async def invalidate_all(self, user_id: str) -> None:
        await self._session.execute(
            update(RecoveryCode)
            .where(
                RecoveryCode.user_id == user_id,
                RecoveryCode.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
        await self._session.flush()

    async def count_unused(self, user_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(RecoveryCode)
            .where(
                RecoveryCode.user_id == user_id,
                RecoveryCode.used_at.is_(None),
            )
        )
        return result.scalar_one()

    async def get_all_for_user(self, user_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(RecoveryCode).where(RecoveryCode.user_id == user_id)
        )
        return [_to_dict(obj) for obj in result.scalars().all()]
