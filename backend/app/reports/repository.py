from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class AbstractReportRepository(ABC):
    @abstractmethod
    async def attendance_report(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def member_attendance_rates(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def members_report(self) -> list[dict[str, Any]]: ...


class SqlReportRepository(AbstractReportRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def attendance_report(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        from sqlalchemy import func, select

        from app.attendance.db_models import Attendance
        from app.sessions.db_models import SessionInstance

        # Query sessions in date range
        stmt = select(SessionInstance).where(
            SessionInstance.date >= date_from,
            SessionInstance.date <= date_to,
            SessionInstance.cancelled.is_(False),
        )
        result = await self._session.execute(stmt)
        sessions = result.scalars().all()

        rows = []
        for session in sessions:
            count_stmt = select(func.count()).where(Attendance.session_id == session.id)
            count_result = await self._session.execute(count_stmt)
            headcount = count_result.scalar() or 0
            rows.append(
                {
                    "session_id": session.id,
                    "date": session.date,
                    "headcount": headcount,
                }
            )
        return rows

    async def member_attendance_rates(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """Attendance Rate (GLOSSARY.md) for each Member who attended in range.

        Both sides count only held Sessions on or after the later of
        date_from and the Member's join date.
        """
        from sqlalchemy import func, select

        from app.attendance.db_models import Attendance
        from app.members.db_models import Member
        from app.sessions.db_models import SessionInstance

        held = select(SessionInstance.date).where(
            SessionInstance.date >= date_from,
            SessionInstance.date <= date_to,
            SessionInstance.cancelled.is_(False),
        )
        held_dates = (await self._session.execute(held)).scalars().all()

        att_stmt = (
            select(
                Member.id,
                Member.display_name,
                Member.first_name,
                Member.surname,
                Member.join_date,
                func.count().label("cnt"),
            )
            .select_from(Attendance)
            .join(Member, Member.id == Attendance.member_id)
            .join(SessionInstance, SessionInstance.id == Attendance.session_id)
            .where(
                SessionInstance.date >= date_from,
                SessionInstance.date <= date_to,
                SessionInstance.cancelled.is_(False),
                SessionInstance.date >= Member.join_date,
            )
            .group_by(Member.id)
        )

        rows = []
        for member_id, display_name, first_name, surname, join_date, count in (
            await self._session.execute(att_stmt)
        ).all():
            # ISO date strings compare in date order.
            total = sum(1 for d in held_dates if d >= join_date)
            rows.append(
                {
                    "member_id": member_id,
                    "display_name": display_name or f"{first_name} {surname}",
                    "sessions_attended": count,
                    "total_sessions": total,
                    "attendance_rate": round(count / total, 4),
                }
            )
        return rows

    async def members_report(self) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.grades.db_models import GradeHistory
        from app.members.db_models import Member

        members_result = await self._session.execute(select(Member))
        members = members_result.scalars().all()

        rows = []
        for member in members:
            grades_result = await self._session.execute(
                select(GradeHistory)
                .where(GradeHistory.member_id == member.id)
                .order_by(GradeHistory.promoted_at.desc())
                .limit(1)
            )
            latest_grade = grades_result.scalar_one_or_none()
            rows.append(
                {
                    "member_id": member.id,
                    "display_name": member.display_name
                    or f"{member.first_name} {member.surname}",
                    "join_date": member.join_date,
                    "current_grade": latest_grade.grade if latest_grade else None,
                }
            )
        return rows
