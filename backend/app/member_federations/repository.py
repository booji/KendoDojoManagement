from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.member_federations.db_models import MemberFederation


class MemberFederationRecord(BaseModel):
    """What the repository hands back for one federation membership.

    Owned by the repository, not by the HTTP layer: `MemberFederationResponse`
    is a response contract and carries a derived `renewal_status` the database
    knows nothing about. Keeping them apart lets either change without
    dragging the other along.

    `renewal_date` is an ISO string here, always. It used to be whatever the
    writing path happened to leave behind, which is why callers reached for
    `hasattr(value, "isoformat")` — in the router and in this module both
    (#345).
    """

    id: str
    member_id: str
    federation_id: str
    member_number: str
    renewal_date: str | None = None


@runtime_checkable
class AbstractMemberFederationRepository(Protocol):
    async def get(self, membership_id: str) -> MemberFederationRecord | None: ...

    async def get_for_member(self, member_id: str) -> list[MemberFederationRecord]: ...

    async def add(self, data: dict[str, Any]) -> MemberFederationRecord: ...

    async def update(
        self, membership_id: str, data: dict[str, Any]
    ) -> MemberFederationRecord | None: ...

    async def remove(self, membership_id: str) -> bool: ...


_COLUMNS = frozenset({"member_id", "federation_id", "member_number", "renewal_date"})


def _to_record(obj: MemberFederation) -> MemberFederationRecord:
    return MemberFederationRecord(
        id=obj.id,
        member_id=obj.member_id,
        federation_id=obj.federation_id,
        member_number=obj.member_number,
        renewal_date=obj.renewal_date.isoformat() if obj.renewal_date else None,
    )


def _writable(data: dict[str, Any]) -> dict[str, Any]:
    """Normalise a write, refusing anything that is not a column.

    `renewal_date` is stored as a `date`, whichever of the two a caller
    supplies. Callers used to convert first — and the conversion they applied
    produced a string, which the `Date` column rejects outright, so writing a
    renewal date through the API raised a `DataError` from asyncpg. The four
    coercion sites in the router made it look handled; nothing exercised it,
    because the e2e tests covering renewal dates are all `xfail` placeholders.

    An unknown key raises rather than being dropped: a write that reports
    success and stores nothing is worse than one that fails.
    """
    unknown = set(data) - _COLUMNS
    if unknown:
        raise TypeError(
            f"{sorted(unknown)} is not a column of member_federations. "
            f"Known columns: {sorted(_COLUMNS)}"
        )
    normalised = dict(data)
    renewal = normalised.get("renewal_date")
    if isinstance(renewal, str):
        normalised["renewal_date"] = date.fromisoformat(renewal)
    return normalised


class SqlMemberFederationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, membership_id: str) -> MemberFederationRecord | None:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.id == membership_id)
        )
        obj = result.scalar_one_or_none()
        return _to_record(obj) if obj else None

    async def get_for_member(self, member_id: str) -> list[MemberFederationRecord]:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.member_id == member_id)
        )
        return [_to_record(r) for r in result.scalars().all()]

    async def add(self, data: dict[str, Any]) -> MemberFederationRecord:
        obj = MemberFederation(**_writable(data))
        self._session.add(obj)
        await self._session.flush()
        return _to_record(obj)

    async def update(
        self, membership_id: str, data: dict[str, Any]
    ) -> MemberFederationRecord | None:
        result = await self._session.execute(
            select(MemberFederation).where(MemberFederation.id == membership_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in _writable(data).items():
            setattr(obj, key, value)
        await self._session.flush()
        return _to_record(obj)

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
