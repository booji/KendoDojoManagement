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

    @abstractmethod
    async def grade_distribution(self, statuses: list[str]) -> list[dict[str, Any]]: ...


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

        att_stmt = (
            select(Attendance.member_id, func.count().label("cnt"))
            .where(
                Attendance.session_id.in_(session_ids),
                Attendance.member_id.is_not(None),
            )
            .group_by(Attendance.member_id)
        )

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

        from app.grades.repository import SqlGradeRepository
        from app.members.db_models import Member

        members_result = await self._session.execute(select(Member))
        members = members_result.scalars().all()

        grades = SqlGradeRepository(self._session)
        rows = []
        for member in members:
            current = await grades.get_current_grade(member.id)
            rows.append(
                {
                    "member_id": member.id,
                    "display_name": member.display_name
                    or f"{member.first_name} {member.surname}",
                    "join_date": member.join_date,
                    "current_grade": current["grade"] if current else None,
                }
            )
        return rows

    async def grade_distribution(self, statuses: list[str]) -> list[dict[str, Any]]:
        """How many Members with one of these Membership Statuses hold each
        Grade, today: Mukyū up to the highest Grade held, zeros kept.

        Visitors are not Members, so they are never counted.
        """
        from collections import Counter

        from sqlalchemy import select

        from app.grades.models import Grade
        from app.grades.repository import SqlGradeRepository
        from app.members.db_models import Member

        result = await self._session.execute(
            select(Member.id).where(Member.membership_status.in_(statuses))
        )
        member_ids = list(result.scalars().all())
        if not member_ids:
            return []
        current = await SqlGradeRepository(self._session).get_current_grades(member_ids)
        counts = Counter(
            current[m]["grade"] if m in current else Grade.MUKYUU for m in member_ids
        )
        grades = list(Grade)
        highest = max(grades.index(Grade(g)) for g in counts)
        return [
            {"grade": g.value, "display_name": g.display_name, "count": counts[g]}
            for g in grades[: highest + 1]
        ]
