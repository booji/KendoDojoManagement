"""Recovery code repository — create, query, invalidate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import AdminRecoveryToken, RecoveryCode


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

    async def get_unused_codes_with_hash(
        self, user_id: str
    ) -> list[dict[str, Any]]: ...

    async def mark_used(self, code_id: str) -> None: ...


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

    async def get_unused_codes_with_hash(self, user_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user_id,
                RecoveryCode.used_at.is_(None),
            )
        )
        return [
            {**_to_dict(obj), "code_hash": obj.code_hash}
            for obj in result.scalars().all()
        ]

    async def mark_used(self, code_id: str) -> None:
        await self._session.execute(
            update(RecoveryCode)
            .where(RecoveryCode.id == code_id)
            .values(used_at=datetime.now(UTC))
        )
        await self._session.flush()


# ── Admin recovery token protocol + implementation ────────────────────────────


def _admin_token_to_dict(obj: AdminRecoveryToken) -> dict[str, Any]:
    return {
        "id": obj.id,
        "user_id": obj.user_id,
        "created_by_id": obj.created_by_id,
        "token_hash": obj.token_hash,
        "expires_at": obj.expires_at,
        "used_at": obj.used_at,
        "created_at": obj.created_at,
    }


@runtime_checkable
class AbstractAdminTokenRepository(Protocol):
    async def create_admin_token(
        self,
        user_id: str,
        created_by_id: str | None,
        token_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]: ...

    async def get_live_admin_tokens_for_user(
        self, user_id: str
    ) -> list[dict[str, Any]]: ...

    async def mark_admin_token_used(self, token_id: str) -> None: ...


class SqlAdminTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_admin_token(
        self,
        user_id: str,
        created_by_id: str | None,
        token_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        # One live token per Account: issuing a new one expires the rest, so a
        # redeem never compares more hashes than its padding covers (#594).
        await self._session.execute(
            update(AdminRecoveryToken)
            .where(
                AdminRecoveryToken.user_id == user_id,
                AdminRecoveryToken.used_at.is_(None),
                AdminRecoveryToken.expires_at > func.now(),
            )
            .values(expires_at=func.now())
        )
        obj = AdminRecoveryToken(
            user_id=user_id,
            created_by_id=created_by_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(obj)
        await self._session.flush()
        return _admin_token_to_dict(obj)

    async def get_live_admin_tokens_for_user(
        self, user_id: str
    ) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(AdminRecoveryToken).where(
                AdminRecoveryToken.user_id == user_id,
                AdminRecoveryToken.used_at.is_(None),
                AdminRecoveryToken.expires_at > func.now(),
            )
        )
        return [_admin_token_to_dict(obj) for obj in result.scalars().all()]

    async def mark_admin_token_used(self, token_id: str) -> None:
        await self._session.execute(
            update(AdminRecoveryToken)
            .where(AdminRecoveryToken.id == token_id)
            .values(used_at=datetime.now(UTC))
        )
        await self._session.flush()
