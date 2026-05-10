from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import bcrypt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.db_models import Attendance, CheckinToken
from app.members.db_models import Member
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
            select(Attendance, Member.full_name)
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
            {**_attendance_to_dict(row.Attendance), "display_name": row.full_name}
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
            select(Attendance, Member.full_name)
            .outerjoin(Member, or_(Attendance.member_id == Member.id, Attendance.member_id == Member.user_id))
            .where(Attendance.id == obj.id)
        )
        row = result.one()
        return {**_attendance_to_dict(row.Attendance), "display_name": row.full_name}

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
            select(SessionInstance).where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        return _instance_to_dict(obj) if obj else None

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance).where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        await self._session.flush()
        return _instance_to_dict(obj)
