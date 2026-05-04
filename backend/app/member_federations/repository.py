from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.member_federations.db_models import MemberFederation


@runtime_checkable
class AbstractMemberFederationRepository(Protocol):
    async def get(self, membership_id: str) -> dict[str, Any] | None: ...

    async def get_for_member(self, member_id: str) -> list[dict[str, Any]]: ...

    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def update(
        self, membership_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def remove(self, membership_id: str) -> bool: ...


def _to_dict(obj: MemberFederation) -> dict[str, Any]:
    renewal = obj.renewal_date
    return {
        "id": obj.id,
        "member_id": obj.member_id,
        "federation_id": obj.federation_id,
        "member_number": obj.member_number,
        "renewal_date": renewal.isoformat() if renewal is not None else None,
    }


class SqlMemberFederationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, membership_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.id == membership_id)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def get_for_member(self, member_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.member_id == member_id)
        )
        return [_to_dict(r) for r in result.scalars().all()]

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        row_data = {**data}
        if hasattr(row_data.get("renewal_date"), "isoformat"):
            row_data["renewal_date"] = row_data["renewal_date"]
        obj = MemberFederation(**row_data)
        self._session.add(obj)
        await self._session.flush()
        return _to_dict(obj)

    async def update(
        self, membership_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.id == membership_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        await self._session.flush()
        return _to_dict(obj)

    async def remove(self, membership_id: str) -> bool:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.id == membership_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return False
        await self._session.delete(obj)
        await self._session.flush()
        return True
