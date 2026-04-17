from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class AbstractDashboardRepository(ABC):
    @abstractmethod
    async def active_member_count(self) -> int: ...

    @abstractmethod
    async def sessions_this_week(self) -> int: ...

    @abstractmethod
    async def attendance_rate_for_period(
        self, date_from: date, date_to: date
    ) -> float: ...


class StubDashboardRepository(AbstractDashboardRepository):
    """In-memory stub for testing — no DB required."""

    def __init__(
        self,
        active_members: int = 0,
        sessions_this_week_count: int = 0,
        attendance_rate: float = 0.0,
    ) -> None:
        self._active_members = active_members
        self._sessions_this_week_count = sessions_this_week_count
        self._attendance_rate = attendance_rate

    async def active_member_count(self) -> int:
        return self._active_members

    async def sessions_this_week(self) -> int:
        return self._sessions_this_week_count

    async def attendance_rate_for_period(self, date_from: date, date_to: date) -> float:
        return self._attendance_rate


class SqlDashboardRepository(AbstractDashboardRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active_member_count(self) -> int:
        from sqlalchemy import func, select

        from app.members.db_models import Member

        result = await self._session.execute(
            select(func.count()).where(Member.membership_status == "active")
        )
        return result.scalar() or 0

    async def sessions_this_week(self) -> int:
        from sqlalchemy import func, select

        from app.sessions.db_models import SessionInstance

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        result = await self._session.execute(
            select(func.count()).where(
                SessionInstance.date >= week_start.isoformat(),
                SessionInstance.date <= week_end.isoformat(),
            )
        )
        return result.scalar() or 0

    async def attendance_rate_for_period(self, date_from: date, date_to: date) -> float:
        from sqlalchemy import func, select

        from app.attendance.db_models import Attendance
        from app.sessions.db_models import SessionInstance

        sess_res = await self._session.execute(
            select(SessionInstance.id).where(
                SessionInstance.date >= date_from.isoformat(),
                SessionInstance.date <= date_to.isoformat(),
            )
        )
        session_ids = [row[0] for row in sess_res.all()]
        if not session_ids:
            return 0.0

        active_count = await self.active_member_count()
        total_slots = len(session_ids) * (active_count or 1)

        att_res = await self._session.execute(
            select(func.count()).where(
                Attendance.session_id.in_(session_ids),
                Attendance.member_id.is_not(None),
            )
        )
        attended: int = att_res.scalar() or 0
        return round(attended / total_slots, 4)


def get_admin_stats_from_repo(repo: AbstractDashboardRepository) -> Any:
    """Helper kept for backward compatibility — not used by router."""
    pass
