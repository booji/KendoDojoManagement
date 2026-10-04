"""Recovery attempt repository — log and count redemption attempts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import RecoveryAttempt

# Attempt rows outlive this only for an Account that keeps failing and never
# succeeds -- they must, since lockout counts failures with no time window --
# but their IP addresses do not (#434).
IP_RETENTION = timedelta(days=30)


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
        now = datetime.now(UTC)
        # No scheduler in the app, so retention runs whenever an attempt is
        # logged, for every Account. It runs before the DELETE below so
        # concurrent redemptions take row locks in the same order.
        await self._session.execute(
            update(RecoveryAttempt)
            .where(
                RecoveryAttempt.attempted_at < now - IP_RETENTION,
                RecoveryAttempt.ip_address.is_not(None),
            )
            .values(ip_address=None)
        )
        if success:
            # Earlier rows no longer count toward lockout; they are only
            # stored IP addresses (#434).
            await self._session.execute(
                delete(RecoveryAttempt).where(RecoveryAttempt.user_id == user_id)
            )
        obj = RecoveryAttempt(
            user_id=user_id,
            attempted_at=now,
            ip_address=ip_address,
            success=success,
        )
        self._session.add(obj)
        await self._session.flush()
