from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import bcrypt
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.db_models import Attendance, CheckinToken
from app.members.db_models import Member
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
        self, session_ids: list[str], member_id: str
    ) -> dict[str, dict[str, Any]]: ...


@runtime_checkable
class AbstractCheckinTokenRepository(Protocol):
    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]: ...

    async def get(self, token: str) -> dict[str, Any] | None: ...

    async def redeem(self, token: str) -> dict[str, Any] | None: ...


@runtime_checkable
class AbstractSessionInstanceRepository(Protocol):
    async def get(self, instance_id: str) -> dict[str, Any] | None: ...

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...


def _attendance_to_dict(obj: Attendance) -> dict[str, Any]:
    return {
        "id": obj.id,
        "session_id": obj.session_id,
        "member_id": obj.member_id,
        "visitor_name": obj.visitor_name,
        "checked_in_at": obj.checked_in_at,
        "recorded_by": obj.recorded_by,
    }


def _token_to_dict(obj: CheckinToken, plaintext: str | None = None) -> dict[str, Any]:
    return {
        "token": plaintext if plaintext is not None else obj.token,
        "session_id": obj.session_id,
        "expires_at": obj.expires_at,
        "used_at": obj.used_at,
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
            .outerjoin(
                Member,
                or_(
                    Attendance.member_id == Member.id,
                    Attendance.member_id == Member.user_id,
                ),
            )
            .where(Attendance.session_id == session_id)
        )
        return [
            {
                **_attendance_to_dict(row.Attendance),
                "display_name": row.display_name
                or (f"{row.first_name} {row.surname}" if row.first_name else None),
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
            .outerjoin(
                Member,
                or_(
                    Attendance.member_id == Member.id,
                    Attendance.member_id == Member.user_id,
                ),
            )
            .where(Attendance.id == obj.id)
        )
        row = result.one()
        return {
            **_attendance_to_dict(row.Attendance),
            "display_name": row.display_name
            or (f"{row.first_name} {row.surname}" if row.first_name else None),
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
            select(Attendance).where(Attendance.member_id == member_id)
        )
        return [_attendance_to_dict(row) for row in result.scalars().all()]

    async def summary_for_sessions(
        self, session_ids: list[str], member_id: str
    ) -> dict[str, dict[str, Any]]:
        """Attendance count, and whether member_id is among the attendees, for
        every requested session -- in one query.

        Deliberately no join against Member: a count needs no display name, and
        the caller (GET /sessions) wants two numbers per session, not rows.

        member_id is compared by plain equality, matching what the per-session
        loop this replaced did. Note that attendance.member_id holds a User id
        for a self check-in and a Member id for an admin-marked one -- see
        issue #340. Preserved rather than fixed here: what "checked in" should
        mean for an admin-marked member is a behaviour question, not a
        performance one.
        """
        if not session_ids:
            return {}

        result = await self._session.execute(
            select(
                Attendance.session_id,
                func.count().label("attendance_count"),
                func.count()
                .filter(Attendance.member_id == member_id)
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


class SqlCheckinTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _token_lookup(plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode()).hexdigest()

    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]:
        plaintext = secrets.token_urlsafe(32)
        token_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
        obj = CheckinToken(
            token=token_hash,
            token_lookup=self._token_lookup(plaintext),
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        self._session.add(obj)
        await self._session.flush()
        return _token_to_dict(obj, plaintext=plaintext)

    async def _find_by_plaintext(
        self, token: str, *, for_update: bool = False
    ) -> CheckinToken | None:
        q = select(CheckinToken).where(
            CheckinToken.token_lookup == self._token_lookup(token)
        )
        if for_update:
            q = q.with_for_update()
        result = await self._session.execute(q)
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        if not bcrypt.checkpw(token.encode(), obj.token.encode()):
            return None
        return obj

    async def get(self, token: str) -> dict[str, Any] | None:
        obj = await self._find_by_plaintext(token)
        return _token_to_dict(obj, plaintext=token) if obj else None

    async def redeem(self, token: str) -> dict[str, Any] | None:
        obj = await self._find_by_plaintext(token, for_update=True)
        if obj is None:
            return None
        if obj.used_at is not None:
            raise ValueError("Token already used")
        obj.used_at = datetime.now(UTC)
        await self._session.flush()
        return _token_to_dict(obj, plaintext=token)


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

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance)
            .options(selectinload(SessionInstance.segments))
            .where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        await self._session.flush()
        return _instance_to_dict(obj)
