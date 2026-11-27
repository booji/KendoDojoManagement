from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.db_models import Attendance
from app.members.db_models import Member
from app.members.schemas import member_name
from app.sessions.db_models import SessionInstance
from app.sessions.envelope import session_time_envelope


@runtime_checkable
class AbstractAttendanceRepository(Protocol):
    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]: ...

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]: ...

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None: ...

    async def admin_mark_attended(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]: ...

    async def remove_attendance(self, session_id: str, member_id: str) -> bool: ...

    async def add_visitor(
        self, session_id: str, visitor_name: str, recorded_by: str
    ) -> dict[str, Any]: ...

    async def list_for_member(self, member_id: str) -> list[dict[str, Any]]: ...

    async def summary_for_sessions(
        self, session_ids: list[str], member_id: str | None
    ) -> dict[str, dict[str, Any]]: ...


@runtime_checkable
class AbstractSessionInstanceRepository(Protocol):
    async def get(self, instance_id: str) -> dict[str, Any] | None: ...


def _attendance_to_dict(obj: Attendance) -> dict[str, Any]:
    return {
        "id": obj.id,
        "session_id": obj.session_id,
        "member_id": obj.member_id,
        "visitor_name": obj.visitor_name,
        "checked_in_at": obj.checked_in_at,
        "recorded_by": obj.recorded_by,
    }


def _instance_to_dict(obj: SessionInstance) -> dict[str, Any]:
    segments = [
        {"start_time": s.start_time, "duration_minutes": s.duration_minutes}
        for s in obj.segments
    ]
    start_time, end_time = (
        session_time_envelope(segments) if segments else ("00:00", "00:00")
    )
    return {
        "id": obj.id,
        "date": obj.date,
        "cancelled": obj.cancelled,
        "start_time": start_time,
        "end_time": end_time,
        "checkin_window_before_minutes": obj.checkin_window_before_minutes,
        "checkin_window_after_minutes": obj.checkin_window_after_minutes,
    }


class SqlAttendanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        obj = Attendance(
            session_id=session_id,
            member_id=member_id,
            checked_in_at=datetime.now(UTC).isoformat(),
            recorded_by=recorded_by,
        )
        self._session.add(obj)
        await self._session.flush()
        return _attendance_to_dict(obj)

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(Attendance, Member.display_name, Member.first_name, Member.surname)
            .outerjoin(Member, Attendance.member_id == Member.id)
            .where(Attendance.session_id == session_id)
        )
        return [
            {
                **_attendance_to_dict(row.Attendance),
                "display_name": member_name(
                    row.display_name, row.first_name, row.surname
                ),
            }
            for row in result.all()
        ]

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Attendance).where(
                Attendance.session_id == session_id,
                Attendance.member_id == member_id,
            )
        )
        obj = result.scalar_one_or_none()
        return _attendance_to_dict(obj) if obj else None

    async def admin_mark_attended(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        obj = Attendance(
            session_id=session_id,
            member_id=member_id,
            visitor_name=None,
            checked_in_at=datetime.now(UTC).isoformat(),
            recorded_by=recorded_by,
        )
        self._session.add(obj)
        await self._session.flush()
        result = await self._session.execute(
            select(Attendance, Member.display_name, Member.first_name, Member.surname)
            .outerjoin(Member, Attendance.member_id == Member.id)
            .where(Attendance.id == obj.id)
        )
        row = result.one()
        return {
            **_attendance_to_dict(row.Attendance),
            "display_name": member_name(row.display_name, row.first_name, row.surname),
        }

    async def remove_attendance(self, session_id: str, member_id: str) -> bool:
        result = await self._session.execute(
            select(Attendance).where(
                Attendance.session_id == session_id,
                Attendance.member_id == member_id,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return False
        await self._session.delete(obj)
        await self._session.flush()
        return True

    async def add_visitor(
        self, session_id: str, visitor_name: str, recorded_by: str
    ) -> dict[str, Any]:
        obj = Attendance(
            session_id=session_id,
            member_id=None,
            visitor_name=visitor_name,
            checked_in_at=datetime.now(UTC).isoformat(),
            recorded_by=recorded_by,
        )
        self._session.add(obj)
        await self._session.flush()
        return _attendance_to_dict(obj)

    async def list_for_member(self, member_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(Attendance, SessionInstance.title, SessionInstance.date)
            .join(SessionInstance, Attendance.session_id == SessionInstance.id)
            .where(Attendance.member_id == member_id)
            .order_by(SessionInstance.date.desc(), Attendance.checked_in_at.desc())
        )
        return [
            {
                **_attendance_to_dict(row.Attendance),
                "session_title": row.title,
                "session_date": row.date,
            }
            for row in result.all()
        ]

    async def summary_for_sessions(
        self, session_ids: list[str], member_id: str | None
    ) -> dict[str, dict[str, Any]]:
        """Attendance count, and whether member_id is among the attendees, for
        every requested session -- in one query.

        Deliberately no join against Member: a count needs no display name, and
        the caller (GET /sessions) wants two numbers per session, not rows.

        member_id is a Member id however the attendance was recorded (#340), so
        plain equality answers "am I checked in" for an admin-marked member as
        well as a self check-in. A caller with no member record (member_id
        None) is never checked in -- comparing against NULL would instead
        match every visitor row, which has a NULL member_id.
        """
        if not session_ids:
            return {}

        result = await self._session.execute(
            select(
                Attendance.session_id,
                func.count().label("attendance_count"),
                func.count()
                .filter(
                    false() if member_id is None else Attendance.member_id == member_id
                )
                .label("own_records"),
            )
            .where(Attendance.session_id.in_(session_ids))
            .group_by(Attendance.session_id)
        )
        found = {
            row.session_id: {
                "attendance_count": row.attendance_count,
                "is_checked_in": row.own_records > 0,
            }
            for row in result.all()
        }
        return {
            session_id: found.get(
                session_id, {"attendance_count": 0, "is_checked_in": False}
            )
            for session_id in session_ids
        }


class SqlSessionInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance)
            .options(selectinload(SessionInstance.segments))
            .where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        return _instance_to_dict(obj) if obj else None
