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
        )
        result = await self._session.execute(stmt)
        sessions = result.scalars().all()

        rows = []
        for session in sessions:
            count_stmt = select(func.count()).where(
                Attendance.session_id == session.id
            )
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
        from sqlalchemy import func, select

        from app.attendance.db_models import Attendance
        from app.sessions.db_models import SessionInstance

        sessions_stmt = select(SessionInstance).where(
            SessionInstance.date >= date_from,
            SessionInstance.date <= date_to,
        )
        sessions_result = await self._session.execute(sessions_stmt)
        sessions = sessions_result.scalars().all()
        total = len(sessions)
        session_ids = [s.id for s in sessions]

        if not session_ids:
            return []

        att_stmt = select(
            Attendance.member_id, func.count().label("cnt")
        ).where(
            Attendance.session_id.in_(session_ids),
            Attendance.member_id.is_not(None),
        ).group_by(Attendance.member_id)

        att_result = await self._session.execute(att_stmt)
        rows = []
        for member_id, count in att_result.all():
            rows.append(
                {
                    "member_id": member_id,
                    "sessions_attended": count,
                    "total_sessions": total,
                    "attendance_rate": round(count / total, 4) if total > 0 else 0.0,
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
                    "full_name": member.full_name,
                    "join_date": member.join_date,
                    "current_grade": latest_grade.grade if latest_grade else None,
                }
            )
        return rows
