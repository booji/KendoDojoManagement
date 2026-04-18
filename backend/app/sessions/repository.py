from __future__ import annotations

import json
from datetime import date
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sessions.db_models import SessionInstance, SessionTemplate, SessionType


@runtime_checkable
class AbstractSessionTypeRepository(Protocol):
    async def add(self, name: str) -> dict[str, Any]: ...

    async def get_by_name(self, name: str) -> dict[str, Any] | None: ...

    async def list(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class AbstractSessionTemplateRepository(Protocol):
    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, template_id: str) -> dict[str, Any] | None: ...

    async def list(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class AbstractSessionInstanceRepository(Protocol):
    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, instance_id: str) -> dict[str, Any] | None: ...

    async def list(self) -> list[dict[str, Any]]: ...

    async def list_upcoming(
        self, as_of: date | None = None
    ) -> list[dict[str, Any]]: ...

    async def list_in_range(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]: ...

    async def latest_date_for_template(self, template_id: str) -> date | None: ...

    async def cancel(self, instance_id: str) -> dict[str, Any] | None: ...


def _type_to_dict(obj: SessionType) -> dict[str, Any]:
    return {"id": obj.id, "name": obj.name}


def _template_to_dict(obj: SessionTemplate) -> dict[str, Any]:
    raw_days = obj.recurrence_days
    if raw_days is None:
        recurrence_days: list[int] = []
    elif isinstance(raw_days, str):
        try:
            recurrence_days = json.loads(raw_days)
        except json.JSONDecodeError:
            recurrence_days = []
    else:
        recurrence_days = raw_days  # type: ignore[assignment]
    return {
        "id": obj.id,
        "session_type_id": obj.session_type_id,
        "title": obj.title,
        "start_date": obj.start_date,
        "start_time": obj.start_time,
        "duration_minutes": obj.duration_minutes,
        "recurrence": obj.recurrence,
        "day_of_week": obj.day_of_week,
        "location": obj.location,
        "recurrence_days": recurrence_days,
        "interval_weeks": obj.interval_weeks if obj.interval_weeks is not None else 1,
        "info": obj.info,
        "coach_notes": obj.coach_notes,
    }


def _instance_to_dict(obj: SessionInstance) -> dict[str, Any]:
    # Combine date + start_time into an ISO-8601 datetime string for the frontend.
    scheduled_at = f"{obj.date}T{obj.start_time}:00"
    return {
        "id": obj.id,
        "session_type_id": obj.session_type_id,
        "scheduled_at": scheduled_at,
        "duration_minutes": obj.duration_minutes,
        "location": obj.location,
        "template_id": obj.template_id,
        "status": "cancelled" if obj.cancelled else "scheduled",
        # Keep raw fields for internal / admin use
        "date": obj.date,
        "start_time": obj.start_time,
        "cancelled": obj.cancelled,
        "notes": obj.notes,
        "info": obj.info,
        "coach_notes": obj.coach_notes,
        "checkin_url": obj.checkin_url,
    }


class SqlSessionTypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, name: str) -> dict[str, Any]:
        existing = await self.get_by_name(name)
        if existing:
            raise ValueError(f"Session type '{name}' already exists")
        obj = SessionType(name=name)
        self._session.add(obj)
        await self._session.flush()
        return _type_to_dict(obj)

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionType).where(SessionType.name == name)
        )
        obj = result.scalar_one_or_none()
        return _type_to_dict(obj) if obj else None

    async def list(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(SessionType))
        return [_type_to_dict(row) for row in result.scalars().all()]


class SqlSessionTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        # Serialize recurrence_days list to JSON string for storage
        serialized = dict(data)
        if "recurrence_days" in serialized and isinstance(
            serialized["recurrence_days"], list
        ):
            serialized["recurrence_days"] = json.dumps(serialized["recurrence_days"])
        obj = SessionTemplate(**serialized)
        self._session.add(obj)
        await self._session.flush()
        return _template_to_dict(obj)

    async def get(self, template_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionTemplate).where(SessionTemplate.id == template_id)
        )
        obj = result.scalar_one_or_none()
        return _template_to_dict(obj) if obj else None

    async def list(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(SessionTemplate))
        return [_template_to_dict(row) for row in result.scalars().all()]


class SqlSessionInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        obj = SessionInstance(**data)
        self._session.add(obj)
        await self._session.flush()
        return _instance_to_dict(obj)

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance).where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        return _instance_to_dict(obj) if obj else None

    async def list(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(SessionInstance))
        return [_instance_to_dict(row) for row in result.scalars().all()]

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        today = (as_of or date.today()).isoformat()
        result = await self._session.execute(
            select(SessionInstance).where(
                SessionInstance.date >= today,
                SessionInstance.cancelled.is_(False),
            )
        )
        return [_instance_to_dict(row) for row in result.scalars().all()]

    async def list_in_range(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        from_iso = from_date.isoformat()
        to_iso = to_date.isoformat()
        result = await self._session.execute(
            select(SessionInstance).where(
                SessionInstance.date >= from_iso,
                SessionInstance.date <= to_iso,
                SessionInstance.cancelled.is_(False),
            )
        )
        return [_instance_to_dict(row) for row in result.scalars().all()]

    async def latest_date_for_template(self, template_id: str) -> date | None:
        result = await self._session.execute(
            select(SessionInstance.date).where(
                SessionInstance.template_id == template_id,
                SessionInstance.cancelled.is_(False),
            )
        )
        dates = [date.fromisoformat(row) for row in result.scalars().all()]
        return max(dates) if dates else None

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance).where(SessionInstance.id == instance_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.cancelled = True
        await self._session.flush()
        return _instance_to_dict(obj)
