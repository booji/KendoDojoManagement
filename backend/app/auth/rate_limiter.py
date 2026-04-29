import os
from datetime import UTC, datetime, timedelta

from fastapi import Request
from slowapi import Limiter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

AUTH_LOCKOUT_MINUTES: int = int(os.getenv("AUTH_LOCKOUT_MINUTES", "15"))
MAX_FAILURES: int = 10
PER_IP_LIMIT: str = "20/minute"
PER_ACCOUNT_LIMIT: str = "10/minute"


def _real_ip(request: Request) -> str:
    # Use the actual peer IP, not X-Forwarded-For, to prevent spoofing.
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_real_ip)


async def check_lockout(user_id: str, session: AsyncSession) -> bool:
    """Return True if account is currently locked."""
    from app.auth.db_models import User

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return False
    if user.locked_until is None:
        return False
    now = datetime.now(UTC)
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > now


async def record_failure(user_id: str, session: AsyncSession) -> int:
    """Increment DB failure count; lock if >= MAX_FAILURES. Returns new count.

    Caller must commit the session after this call.
    """
    from app.auth.db_models import User

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return 0
    count = (user.login_failures or 0) + 1
    values: dict = {"login_failures": count}
    if count >= MAX_FAILURES:
        values["locked_until"] = datetime.now(UTC) + timedelta(
            minutes=AUTH_LOCKOUT_MINUTES
        )
    await session.execute(update(User).where(User.id == user_id).values(**values))
    return count


async def clear_lockout(user_id: str, session: AsyncSession) -> None:
    """Clear lockout and failure count on successful auth. Caller must commit."""
    from app.auth.db_models import User

    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(locked_until=None, login_failures=0)
    )
