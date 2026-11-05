from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.members.models import MembershipStatus, member_name


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
    async def grade_distribution(
        self, statuses: list[MembershipStatus]
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def headcount(self, date_from: str, date_to: str) -> list[dict[str, Any]]: ...


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
        """Attendance Rate (GLOSSARY.md) for each Member who attended in range,
        and for each active Member who did not (at 0%).

        Both sides count only held Sessions on or after the later of
        date_from and the Member's join date. A Member with no such Session
        is left out rather than listed at 0 of 0.
        """
        from sqlalchemy import and_, func, or_, select

        from app.attendance.db_models import Attendance
        from app.members.db_models import Member
        from app.sessions.db_models import SessionInstance

        held = select(SessionInstance.date).where(
            SessionInstance.date >= date_from,
            SessionInstance.date <= date_to,
            SessionInstance.cancelled.is_(False),
        )
        held_dates = (await self._session.execute(held)).scalars().all()

        attended = (
            select(Attendance.member_id, func.count().label("cnt"))
            .join(Member, Member.id == Attendance.member_id)
            .join(SessionInstance, SessionInstance.id == Attendance.session_id)
            .where(
                SessionInstance.date >= date_from,
                SessionInstance.date <= date_to,
                SessionInstance.cancelled.is_(False),
                SessionInstance.date >= Member.join_date,
            )
            .group_by(Attendance.member_id)
            .subquery()
        )
        stmt = (
            select(
                Member.id,
                Member.display_name,
                Member.first_name,
                Member.surname,
                Member.join_date,
                func.coalesce(attended.c.cnt, 0),
            )
            .outerjoin(attended, attended.c.member_id == Member.id)
            .where(
                or_(
                    attended.c.cnt.is_not(None),
                    and_(
                        Member.membership_status == "active",
                        Member.join_date <= date_to,
                    ),
                )
            )
        )

        rows = []
        for member_id, display_name, first_name, surname, join_date, count in (
            await self._session.execute(stmt)
        ).all():
            # ISO date strings compare in date order.
            total = sum(1 for d in held_dates if d >= join_date)
            if total == 0:
                continue
            rows.append(
                {
                    "member_id": member_id,
                    "display_name": member_name(display_name, first_name, surname),
                    "sessions_attended": count,
                    "total_sessions": total,
                    "attendance_rate": round(count / total, 4),
                }
            )
        return rows

    async def members_report(self) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.grades.repository import SqlGradeRepository
        from app.members.db_models import Member

        members_result = await self._session.execute(select(Member))
        members = members_result.scalars().all()

        grades = await SqlGradeRepository(self._session).get_current_grades(
            [m.id for m in members]
        )
        rows = []
        for member in members:
            current = grades.get(member.id)
            rows.append(
                {
                    "member_id": member.id,
                    "display_name": member_name(
                        member.display_name, member.first_name, member.surname
                    ),
                    "join_date": member.join_date,
                    "current_grade": current["grade"] if current else None,
                }
            )
        return rows

    async def grade_distribution(
        self, statuses: list[MembershipStatus]
    ) -> list[dict[str, Any]]:
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

    async def headcount(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        """Members and Visitors at each held Session in range, oldest first.

        Every Member counts whatever their Membership Status today: a past
        Session's headcount does not change with it.
        """
        from sqlalchemy import func, select

        from app.attendance.db_models import Attendance
        from app.sessions.db_models import SessionInstance

        stmt = (
            select(
                SessionInstance.id,
                SessionInstance.date,
                func.count(Attendance.member_id),
                func.count(Attendance.visitor_name),
            )
            .outerjoin(Attendance, Attendance.session_id == SessionInstance.id)
            .where(
                SessionInstance.date >= date_from,
                SessionInstance.date <= date_to,
                SessionInstance.cancelled.is_(False),
            )
            .group_by(SessionInstance.id, SessionInstance.date)
            .order_by(SessionInstance.date)
        )
        return [
            {"session_id": sid, "date": d, "members": m, "visitors": v}
            for sid, d, m, v in (await self._session.execute(stmt)).all()
        ]
