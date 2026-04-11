from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.db_models import Attendance, CheckinToken
from app.sessions.db_models import SessionInstance


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


@runtime_checkable
class AbstractCheckinTokenRepository(Protocol):
    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]: ...

    async def get(self, token: str) -> dict[str, Any] | None: ...


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


def _token_to_dict(obj: CheckinToken) -> dict[str, Any]:
    return {
        "token": obj.token,
        "session_id": obj.session_id,
        "expires_at": obj.expires_at,
    }


def _instance_to_dict(obj: SessionInstance) -> dict[str, Any]:
    return {
        "id": obj.id,
        "date": obj.date,
        "cancelled": obj.cancelled,
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
            select(Attendance).where(Attendance.session_id == session_id)
        )
        return [_attendance_to_dict(row) for row in result.scalars().all()]

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
        return _attendance_to_dict(obj)

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
            select(Attendance).where(Attendance.member_id == member_id)
        )
        return [_attendance_to_dict(row) for row in result.scalars().all()]


class SqlCheckinTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]:
        obj = CheckinToken(
            token=secrets.token_urlsafe(16),
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        self._session.add(obj)
        await self._session.flush()
        return _token_to_dict(obj)

    async def get(self, token: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(CheckinToken).where(CheckinToken.token == token)
        )
        obj = result.scalar_one_or_none()
        return _token_to_dict(obj) if obj else None


class SqlSessionInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance).where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        return _instance_to_dict(obj) if obj else None
