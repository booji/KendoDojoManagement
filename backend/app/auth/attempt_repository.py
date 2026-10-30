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

    async def clear_expired_ip_addresses(self) -> None:
        """NULL the IP of every Account's attempt row older than IP_RETENTION.

        Run at startup and by the daily kendo-ip-retention timer (#467), not by
        log_attempt. SKIP LOCKED: a row a concurrent redemption holds is being
        deleted or will be cleared next run, and never waiting is what keeps
        this from deadlocking with that redemption's DELETE.
        """
        expired = (
            select(RecoveryAttempt.id)
            .where(
                RecoveryAttempt.attempted_at < datetime.now(UTC) - IP_RETENTION,
                RecoveryAttempt.ip_address.is_not(None),
            )
            .with_for_update(skip_locked=True)
        )
        await self._session.execute(
            update(RecoveryAttempt)
            .where(RecoveryAttempt.id.in_(expired.scalar_subquery()))
            .values(ip_address=None)
        )

    async def log_attempt(
        self, user_id: str, ip_address: str, *, success: bool
    ) -> None:
        now = datetime.now(UTC)
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
