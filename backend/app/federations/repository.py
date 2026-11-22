from __future__ import annotations

import builtins
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.federations.db_models import Federation


@runtime_checkable
class AbstractFederationRepository(Protocol):
    async def get(self, federation_id: str) -> dict[str, Any] | None: ...

    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def update(
        self, federation_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def deactivate(self, federation_id: str) -> dict[str, Any] | None: ...

    async def list(
        self,
        type: str | None = None,
        continental_grouping: str | None = None,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> builtins.list[dict[str, Any]]: ...


def _to_dict(obj: Federation) -> dict[str, Any]:
    return {
        "id": obj.id,
        "name": obj.name,
        "abbreviation": obj.abbreviation,
        "iso_code": obj.iso_code,
        "website": obj.website,
        "continental_grouping": obj.continental_grouping,
        "type": obj.type,
        "is_pinned": obj.is_pinned,
        "is_active": obj.is_active,
    }


class SqlFederationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, federation_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Federation).where(Federation.id == federation_id)
        )
        obj = result.scalar_one_or_none()
        return _to_dict(obj) if obj else None

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        obj = Federation(**data)
        self._session.add(obj)
        await self._session.flush()
        return _to_dict(obj)

    async def update(
        self, federation_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Federation).where(Federation.id == federation_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        await self._session.flush()
        return _to_dict(obj)

    async def deactivate(self, federation_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(Federation).where(Federation.id == federation_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.is_active = False
        await self._session.flush()
        return _to_dict(obj)

    async def list(
        self,
        type: str | None = None,
        continental_grouping: str | None = None,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> builtins.list[dict[str, Any]]:
        stmt = select(Federation)
        if not include_inactive:
            stmt = stmt.where(Federation.is_active.is_(True))
        if type is not None:
            stmt = stmt.where(Federation.type == type)
        if continental_grouping is not None:
            stmt = stmt.where(Federation.continental_grouping == continental_grouping)
        stmt = stmt.order_by(Federation.is_pinned.desc(), asc(Federation.name))
        result = await self._session.execute(stmt)
        rows = [_to_dict(r) for r in result.scalars().all()]
        if search is not None:
            term = search.lower()
            rows = [
                r
                for r in rows
                if r["name"].lower().startswith(term)
                or (r.get("abbreviation") or "").lower().startswith(term)
            ]
        return rows
