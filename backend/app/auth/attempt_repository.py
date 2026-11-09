"""Recovery attempt repository — log and count redemption attempts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import takewhile
from typing import Protocol, runtime_checkable

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import AdminRecoveryToken, RecoveryAttempt

# Attempt rows outlive this only for an Account that keeps failing and never
# succeeds -- they are its audit trail -- but their IP addresses do not (#434).
IP_RETENTION = timedelta(days=30)

# LOCKOUT_THRESHOLD failures within FAILURE_WINDOW, since the Account's last
# success, lock recovery for LOCKOUT_PERIOD after the latest of them; each
# failure past the threshold doubles that, up to MAX_DOUBLINGS (16 hours).
# A lockout always ends: no failure older than FAILURE_WINDOW counts (#580).
LOCKOUT_THRESHOLD = 5
LOCKOUT_PERIOD = timedelta(minutes=15)
MAX_DOUBLINGS = 6
FAILURE_WINDOW = timedelta(hours=24)


@runtime_checkable
class AbstractAttemptRepository(Protocol):
    async def is_locked_out(self, user_id: str) -> bool: ...

    async def log_attempt(
        self, user_id: str, ip_address: str, *, success: bool
    ) -> None: ...


class SqlAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_locked_out(self, user_id: str) -> bool:
        now = datetime.now(UTC)
        since = now - FAILURE_WINDOW
        # Issuing an admin or CLI recovery token clears the Account's
        # failures: only those after it count. The rows stay, as audit.
        last_token_issued = (
            select(func.max(AdminRecoveryToken.created_at))
            .where(AdminRecoveryToken.user_id == user_id)
            .scalar_subquery()
        )
        result = await self._session.execute(
            select(RecoveryAttempt.attempted_at, RecoveryAttempt.success)
            .where(
                RecoveryAttempt.user_id == user_id,
                RecoveryAttempt.attempted_at > since,
                RecoveryAttempt.attempted_at > func.coalesce(last_token_issued, since),
            )
            .order_by(RecoveryAttempt.attempted_at.desc())
        )
        failures = list(takewhile(lambda row: not row.success, result.all()))
        excess = len(failures) - LOCKOUT_THRESHOLD
        if excess < 0:
            return False
        lockout = LOCKOUT_PERIOD * 2 ** min(excess, MAX_DOUBLINGS)
        return now < failures[0].attempted_at + lockout

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
