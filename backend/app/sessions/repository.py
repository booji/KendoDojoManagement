from __future__ import annotations

import json
from datetime import date
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.sessions.db_models import (
    SessionInstance,
    SessionInstanceSegment,
    SessionInstanceSegmentType,
    SessionTemplate,
    SessionTemplateSegment,
    SessionTemplateSegmentType,
    SessionType,
)
from app.sessions.envelope import session_time_envelope


@runtime_checkable
class AbstractSessionTypeRepository(Protocol):
    async def add(self, name: str) -> dict[str, Any]: ...

    async def get_by_name(self, name: str) -> dict[str, Any] | None: ...

    async def get(self, type_id: str) -> dict[str, Any] | None: ...

    async def list(self) -> list[dict[str, Any]]: ...

    async def update(
        self, type_id: str, colour: str | None
    ) -> dict[str, Any] | None: ...

    async def delete(self, type_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class AbstractSessionTemplateRepository(Protocol):
    async def add(self, data: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, template_id: str) -> dict[str, Any] | None: ...

    async def list(self) -> list[dict[str, Any]]: ...

    async def update(
        self, template_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def deactivate(self, template_id: str) -> dict[str, Any] | None: ...


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

    async def cancel(self, instance_id: str) -> dict[str, Any] | None: ...

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def delete(self, instance_id: str) -> dict[str, Any] | None: ...

    async def cancel_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> list[dict[str, Any]]: ...

    async def delete_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> int: ...


def _type_to_dict(obj: SessionType) -> dict[str, Any]:
    return {"id": obj.id, "name": obj.name, "colour": obj.colour}


def _segment_to_dict(
    obj: SessionTemplateSegment | SessionInstanceSegment,
) -> dict[str, Any]:
    return {
        "id": obj.id,
        "start_time": obj.start_time,
        "duration_minutes": obj.duration_minutes,
        "title": obj.title,
        "type_ids": [link.session_type_id for link in obj.type_links],
    }


def _segments_envelope(segments: list[dict[str, Any]]) -> tuple[str, str]:
    if not segments:
        return "00:00", "00:00"
    return session_time_envelope(segments)


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
    segments = [_segment_to_dict(s) for s in obj.segments]
    start_time, end_time = _segments_envelope(segments)
    duration_minutes = _minutes_between(start_time, end_time) if segments else 0
    return {
        "id": obj.id,
        "title": obj.title,
        "start_date": obj.start_date,
        "end_date": obj.end_date,
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "recurrence": obj.recurrence,
        "day_of_week": obj.day_of_week,
        "location": obj.location,
        "recurrence_days": recurrence_days,
        "interval_weeks": obj.interval_weeks if obj.interval_weeks is not None else 1,
        "info": obj.info,
        "coach_notes": obj.coach_notes,
        "is_active": obj.is_active,
        "segments": segments,
    }


def _instance_to_dict(obj: SessionInstance) -> dict[str, Any]:
    segments = [_segment_to_dict(s) for s in obj.segments]
    start_time, end_time = _segments_envelope(segments)
    duration_minutes = _minutes_between(start_time, end_time) if segments else 0
    scheduled_at = f"{obj.date}T{start_time}:00"
    return {
        "id": obj.id,
        "title": obj.title,
        "scheduled_at": scheduled_at,
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "location": obj.location,
        "template_id": obj.template_id,
        "status": "cancelled" if obj.cancelled else "scheduled",
        # Keep raw fields for internal / admin use
        "date": obj.date,
        "cancelled": obj.cancelled,
        "notes": obj.notes,
        "info": obj.info,
        "coach_notes": obj.coach_notes,
        "checkin_window_before_minutes": obj.checkin_window_before_minutes,
        "checkin_window_after_minutes": obj.checkin_window_after_minutes,
        "segments": segments,
    }


def _minutes_between(start: str, end: str) -> int:
    sh, sm = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    return (eh * 60 + em) - (sh * 60 + sm)


def _build_template_segments(
    segments_data: list[dict[str, Any]],
) -> list[SessionTemplateSegment]:
    built = []
    for position, seg in enumerate(segments_data):
        segment = SessionTemplateSegment(
            start_time=seg["start_time"],
            duration_minutes=seg["duration_minutes"],
            title=seg.get("title"),
            position=position,
        )
        segment.type_links = [
            SessionTemplateSegmentType(session_type_id=type_id, position=idx)
            for idx, type_id in enumerate(seg["type_ids"])
        ]
        built.append(segment)
    return built


def _build_instance_segments(
    segments_data: list[dict[str, Any]],
) -> list[SessionInstanceSegment]:
    built = []
    for position, seg in enumerate(segments_data):
        segment = SessionInstanceSegment(
            start_time=seg["start_time"],
            duration_minutes=seg["duration_minutes"],
            title=seg.get("title"),
            position=position,
        )
        segment.type_links = [
            SessionInstanceSegmentType(session_type_id=type_id, position=idx)
            for idx, type_id in enumerate(seg["type_ids"])
        ]
        built.append(segment)
    return built


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

    async def get(self, type_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionType).where(SessionType.id == type_id)
        )
        obj = result.scalar_one_or_none()
        return _type_to_dict(obj) if obj else None

    async def list(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(SessionType))
        return [_type_to_dict(row) for row in result.scalars().all()]

    async def update(self, type_id: str, colour: str | None) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionType).where(SessionType.id == type_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.colour = colour
        await self._session.flush()
        return _type_to_dict(obj)

    async def delete(self, type_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionType).where(SessionType.id == type_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        record = _type_to_dict(obj)
        await self._session.delete(obj)
        await self._session.flush()
        return record


class SqlSessionTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        serialized = dict(data)
        segments_data = serialized.pop("segments", [])
        if "recurrence_days" in serialized and isinstance(
            serialized["recurrence_days"], list
        ):
            serialized["recurrence_days"] = json.dumps(serialized["recurrence_days"])
        obj = SessionTemplate(**serialized)
        obj.segments = _build_template_segments(segments_data)
        self._session.add(obj)
        await self._session.flush()
        # Re-fetch with segments AND their nested type_links eagerly loaded.
        # refresh(["segments"]) reloads segments but not type_links, so
        # serializing would trigger a lazy load outside the async greenlet
        # (sqlalchemy MissingGreenlet -> 500).
        refreshed = await self.get(obj.id)
        assert refreshed is not None
        return refreshed

    async def get(self, template_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionTemplate)
            .where(SessionTemplate.id == template_id)
            .options(
                selectinload(SessionTemplate.segments).selectinload(
                    SessionTemplateSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        return _template_to_dict(obj) if obj else None

    async def list(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(SessionTemplate).options(
                selectinload(SessionTemplate.segments).selectinload(
                    SessionTemplateSegment.type_links
                )
            )
        )
        return [_template_to_dict(row) for row in result.scalars().all()]

    async def update(
        self, template_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionTemplate)
            .where(SessionTemplate.id == template_id)
            .options(
                selectinload(SessionTemplate.segments).selectinload(
                    SessionTemplateSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        data = dict(data)
        segments_data = data.pop("segments", None)
        if "recurrence_days" in data and isinstance(data["recurrence_days"], list):
            data["recurrence_days"] = json.dumps(data["recurrence_days"])
        for key, value in data.items():
            setattr(obj, key, value)
        if segments_data is not None:
            obj.segments = _build_template_segments(segments_data)
        await self._session.flush()
        # Re-fetch with segments AND their nested type_links eagerly loaded.
        # refresh(["segments"]) reloads segments but not type_links, so
        # serializing would trigger a lazy load outside the async greenlet
        # (sqlalchemy MissingGreenlet -> 500).
        refreshed = await self.get(obj.id)
        assert refreshed is not None
        return refreshed

    async def deactivate(self, template_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionTemplate)
            .where(SessionTemplate.id == template_id)
            .options(
                selectinload(SessionTemplate.segments).selectinload(
                    SessionTemplateSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.is_active = False
        await self._session.flush()
        return _template_to_dict(obj)


class SqlSessionInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        serialized = dict(data)
        segments_data = serialized.pop("segments", [])
        obj = SessionInstance(**serialized)
        obj.segments = _build_instance_segments(segments_data)
        self._session.add(obj)
        await self._session.flush()
        # Re-fetch with segments AND their nested type_links eagerly loaded.
        # refresh(["segments"]) reloads segments but not type_links, so
        # serializing would trigger a lazy load outside the async greenlet
        # (sqlalchemy MissingGreenlet -> 500).
        refreshed = await self.get(obj.id)
        assert refreshed is not None
        return refreshed

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance)
            .where(SessionInstance.id == instance_id)
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        return _instance_to_dict(obj) if obj else None

    async def list(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(SessionInstance).options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        return [_instance_to_dict(row) for row in result.scalars().all()]

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        today = (as_of or date.today()).isoformat()
        result = await self._session.execute(
            select(SessionInstance)
            .where(
                SessionInstance.date >= today,
                SessionInstance.cancelled.is_(False),
            )
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        return [_instance_to_dict(row) for row in result.scalars().all()]

    async def list_in_range(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        from_iso = from_date.isoformat()
        to_iso = to_date.isoformat()
        result = await self._session.execute(
            select(SessionInstance)
            .where(
                SessionInstance.date >= from_iso,
                SessionInstance.date <= to_iso,
            )
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        return [_instance_to_dict(row) for row in result.scalars().all()]

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance)
            .where(SessionInstance.id == instance_id)
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        obj.cancelled = True
        await self._session.flush()
        return _instance_to_dict(obj)

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance)
            .where(SessionInstance.id == instance_id)
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        data = dict(data)
        segments_data = data.pop("segments", None)
        for key, value in data.items():
            setattr(obj, key, value)
        if segments_data is not None:
            obj.segments = _build_instance_segments(segments_data)
        await self._session.flush()
        # Re-fetch with segments AND their nested type_links eagerly loaded.
        # refresh(["segments"]) reloads segments but not type_links, so
        # serializing would trigger a lazy load outside the async greenlet
        # (sqlalchemy MissingGreenlet -> 500).
        refreshed = await self.get(obj.id)
        assert refreshed is not None
        return refreshed

    async def delete(self, instance_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(SessionInstance)
            .where(SessionInstance.id == instance_id)
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        record = _instance_to_dict(obj)
        await self._session.delete(obj)
        await self._session.flush()
        return record

    async def cancel_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(SessionInstance)
            .where(
                SessionInstance.template_id == template_id,
                SessionInstance.date >= as_of_date.isoformat(),
                SessionInstance.cancelled.is_(False),
            )
            .options(
                selectinload(SessionInstance.segments).selectinload(
                    SessionInstanceSegment.type_links
                )
            )
        )
        rows = result.scalars().all()
        for obj in rows:
            obj.cancelled = True
        await self._session.flush()
        return [_instance_to_dict(obj) for obj in rows]

    async def delete_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> int:
        result = await self._session.execute(
            select(SessionInstance).where(
                SessionInstance.template_id == template_id,
                SessionInstance.date >= as_of_date.isoformat(),
            )
        )
        rows = result.scalars().all()
        count = len(rows)
        for obj in rows:
            await self._session.delete(obj)
        await self._session.flush()
        return count
