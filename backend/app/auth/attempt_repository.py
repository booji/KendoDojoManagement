"""Recovery attempt repository — log and count redemption attempts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import RecoveryAttempt


@runtime_checkable
class AbstractAttemptRepository(Protocol):
    async def count_failures_since_last_success(self, user_id: str) -> int: ...

    async def log_attempt(
        self, user_id: str, ip_address: str, *, success: bool
    ) -> None: ...


class SqlAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_failures_since_last_success(self, user_id: str) -> int:
        result = await self._session.execute(
            select(RecoveryAttempt)
            .where(RecoveryAttempt.user_id == user_id)
            .order_by(RecoveryAttempt.attempted_at.desc())
        )
        rows = result.scalars().all()
        count = 0
        for row in rows:
            if row.success:
                break
            count += 1
        return count

    async def log_attempt(
        self, user_id: str, ip_address: str, *, success: bool
    ) -> None:
        obj = RecoveryAttempt(
            user_id=user_id,
            attempted_at=datetime.now(UTC),
            ip_address=ip_address,
            success=success,
        )
        self._session.add(obj)
        await self._session.flush()
