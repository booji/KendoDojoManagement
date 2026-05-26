from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.members.db_models import Member


@runtime_checkable
class AbstractMemberRepository(Protocol):
    async def get(self, member_id: str) -> dict[str, Any] | None: ...

    async def get_by_email(self, email: str) -> dict[str, Any] | None: ...

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None: ...

    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def update(
        self, member_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def deactivate(self, member_id: str) -> dict[str, Any] | None: ...

    async def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]: ...


def _to_dict(obj: Member) -> dict[str, Any]:
    return {
        "id": obj.id,
        "email": obj.email,
        "first_name": obj.first_name,
        "surname": obj.surname,
        "display_name": obj.display_name,
        "dob": obj.dob,
        "join_date": obj.join_date,
        "membership_status": obj.membership_status,
        "is_coach": obj.is_coach,
        "is_first_aider": obj.is_first_aider,
        "emergency_contact_name": obj.emergency_contact_name,
        "emergency_contact_phone": obj.emergency_contact_phone,
        "user_id": obj.user_id,
    }


class SqlMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, member_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Member).where(Member.id == member_id)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Member).where(Member.email == email)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Member).where(Member.user_id == user_id)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_by_email(data["email"])
        if existing:
            raise ValueError(f"Member with email '{data['email']}' already exists")
        # Convert date objects to ISO strings for storage
        row_data = {**data}
        if hasattr(row_data.get("dob"), "isoformat"):
            row_data["dob"] = row_data["dob"].isoformat()
        if hasattr(row_data.get("join_date"), "isoformat"):
            row_data["join_date"] = row_data["join_date"].isoformat()
        obj = Member(**row_data)
        self._session.add(obj)
        await self._session.flush()
        return _to_dict(obj)

    async def update(
        self, member_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Member).where(Member.id == member_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in data.items():
            if value is not None and hasattr(obj, key):
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                setattr(obj, key, value)
        await self._session.flush()
        return _to_dict(obj)

    async def deactivate(self, member_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Member).where(Member.id == member_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.membership_status = "inactive"
        await self._session.flush()
        return _to_dict(obj)

    async def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(Member)
        if status is not None:
            stmt = stmt.where(Member.membership_status == status)
        result = await self._session.execute(stmt)
        rows = [_to_dict(r) for r in result.scalars().all()]
        if search is not None:
            term = search.lower()
            rows = [
                r
                for r in rows
                if term in r["first_name"].lower()
                or term in r["surname"].lower()
                or term in r["email"].lower()
            ]
        return rows
