from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class AbstractDojoSettingsRepository(ABC):
    @abstractmethod
    async def get(self) -> dict[str, Any]: ...

    @abstractmethod
    async def update(self, data: dict[str, Any]) -> dict[str, Any]: ...


class StubDojoSettingsRepository(AbstractDojoSettingsRepository):
    """In-memory stub for testing — no DB required."""

    _DEFAULTS: dict[str, Any] = {
        "dojo_name": "My Dojo",
        "logo_url": None,
        "primary_colour": "#4F46E5",
    }

    def __init__(self) -> None:
        self._store: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "updated_at": datetime.utcnow().isoformat(),
            **self._DEFAULTS,
        }

    async def get(self) -> dict[str, Any]:
        return dict(self._store)

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        for key, value in data.items():
            if value is not None:
                self._store[key] = value
        self._store["updated_at"] = datetime.utcnow().isoformat()
        return dict(self._store)


class SqlDojoSettingsRepository(AbstractDojoSettingsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> dict[str, Any]:
        from sqlalchemy import select

        from app.settings.models import DojoSettings

        result = await self._session.execute(select(DojoSettings).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            return {
                "id": None,
                "dojo_name": "My Dojo",
                "logo_url": None,
                "primary_colour": "#4F46E5",
                "updated_at": None,
            }
        return {
            "id": row.id,
            "dojo_name": row.dojo_name,
            "logo_url": row.logo_url,
            "primary_colour": row.primary_colour,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import select

        from app.settings.models import DojoSettings

        result = await self._session.execute(select(DojoSettings).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            row = DojoSettings(id=str(uuid.uuid4()))
            self._session.add(row)
        for key, value in data.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        await self._session.flush()
        return {
            "id": row.id,
            "dojo_name": row.dojo_name,
            "logo_url": row.logo_url,
            "primary_colour": row.primary_colour,
            "updated_at": row.updated_at.isoformat(),
        }
