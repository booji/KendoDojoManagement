from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app import config
from app.attendance.dependencies import get_attendance_repo
from app.attendance.repository import AbstractAttendanceRepository
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from app.sessions.envelope import session_time_envelope
from app.sessions.ical import build_ical
from app.sessions.models import (
    GenerateRequest,
    SessionInstanceCreate,
    SessionInstanceRead,
    SessionInstanceUpdate,
    SessionTemplateCreate,
    SessionTemplateRead,
    SessionTemplateUpdate,
    SessionTypeCreate,
    SessionTypeRead,
    SessionTypeUpdate,
)
from app.sessions.repository import (
    AbstractSessionInstanceRepository,
    AbstractSessionTemplateRepository,
    AbstractSessionTypeRepository,
)
from app.sessions.service import generate_instances, needs_rolling_extension

router = APIRouter(tags=["sessions"])


def _with_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    """Derive start_time/duration_minutes from the session's segments.

    Repositories that already compute the envelope (e.g. the SQL repo) leave
    these fields untouched; stub repositories that store the raw payload
    verbatim get the envelope computed here so the response always carries
    it, regardless of which repository produced the record.
    """
    segments = raw.get("segments") or []
    if not segments:
        return raw
    start_time, end_time = session_time_envelope(segments)
    duration_minutes = _minutes_between(start_time, end_time)
    return {**raw, "start_time": start_time, "duration_minutes": duration_minutes}


def _minutes_between(start: str, end: str) -> int:
    sh, sm = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    return (eh * 60 + em) - (sh * 60 + sm)


def _normalize_instance(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply SessionInstanceRead defaults to fill in any missing optional fields."""
    return SessionInstanceRead.model_validate(_with_envelope(raw)).model_dump()


def _normalize_template(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply SessionTemplateRead defaults to fill in any missing optional fields."""
    return SessionTemplateRead.model_validate(_with_envelope(raw)).model_dump()


_TypeRepo = Annotated[AbstractSessionTypeRepository, Depends(get_session_type_repo)]
_TmplRepo = Annotated[
    AbstractSessionTemplateRepository, Depends(get_session_template_repo)
]
_InstRepo = Annotated[
    AbstractSessionInstanceRepository, Depends(get_session_instance_repo)
]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]
_AttendanceRepo = Annotated[AbstractAttendanceRepository, Depends(get_attendance_repo)]


# ---------------------------------------------------------------------------
# Session types
# ---------------------------------------------------------------------------


@router.get("/session-types")
async def list_session_types(repo: _TypeRepo) -> list[dict[str, Any]]:
    rows = await repo.list()
    return [SessionTypeRead.model_validate(r).model_dump() for r in rows]


@router.put("/session-types/{type_id}")
async def update_session_type(
    type_id: uuid.UUID,
    payload: SessionTypeUpdate,
    _claims: _Admin,
    repo: _TypeRepo,
    uow: _UoW,
) -> dict[str, Any]:
    result = await repo.update(str(type_id), payload.colour)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session type not found"
        )
    await uow.commit()
    return result


def _enrich_segments_with_type_names(
    segments: list[dict[str, Any]], types: dict[str, str]
) -> list[dict[str, Any]]:
    return [
        {**seg, "type_names": [types.get(tid, "") for tid in seg.get("type_ids", [])]}
        for seg in segments
    ]


@router.get("/sessions/ical")
async def get_sessions_ical(repo: _InstRepo, type_repo: _TypeRepo) -> Response:
    sessions = await repo.list_upcoming()
    types = {t["id"]: t["name"] for t in await type_repo.list()}
    origin = os.getenv("PUBLIC_ORIGIN") or os.getenv(
        "WEBAUTHN_ORIGIN", "http://localhost:5173"
    )
    enriched = [
        {
            **s,
            "segments": _enrich_segments_with_type_names(s.get("segments", []), types),
            "checkin_link": f"{origin.rstrip('/')}/checkin/session/{s['id']}",
        }
        for s in sessions
    ]
    content = build_ical(enriched, tz_name=config.TIMEZONE)
    return Response(content=content, media_type="text/calendar; charset=utf-8")


@router.post("/session-types", status_code=status.HTTP_201_CREATED)
async def create_session_type(
    payload: SessionTypeCreate,
    _claims: _Admin,
    repo: _TypeRepo,
    uow: _UoW,
) -> dict[str, Any]:
    try:
        result = await repo.add(payload.name)
        await uow.commit()
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


def _type_referenced_in_segments(segments: list[dict[str, Any]], type_id: str) -> bool:
    return any(type_id in seg.get("type_ids", []) for seg in segments)


def _type_is_referenced(
    type_id: str,
    templates: list[dict[str, Any]],
    instances: list[dict[str, Any]],
) -> bool:
    for record in templates:
        if _type_referenced_in_segments(record.get("segments", []), type_id):
            return True
    for record in instances:
        if _type_referenced_in_segments(record.get("segments", []), type_id):
            return True
    return False


@router.delete("/session-types/{type_id}")
async def delete_session_type(
    type_id: uuid.UUID,
    _claims: _Admin,
    repo: _TypeRepo,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    existing = await repo.get(str(type_id))
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session type not found"
        )
    templates = await template_repo.list()
    instances = await instance_repo.list()
    if _type_is_referenced(str(type_id), templates, instances):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Session type '{existing['name']}' cannot be deleted because it is"
                " referenced by one or more session segments."
            ),
        )
    deleted = await repo.delete(str(type_id))
    await uow.commit()
    return deleted  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Session templates
# ---------------------------------------------------------------------------


@router.post("/sessions/templates", status_code=status.HTTP_201_CREATED)
async def create_session_template(
    payload: SessionTemplateCreate,
    _claims: _Admin,
    repo: _TmplRepo,
    uow: _UoW,
) -> dict[str, Any]:
    result = await repo.add(payload.model_dump())
    await uow.commit()
    return _normalize_template(result)


@router.get("/sessions/templates/{template_id}")
async def get_session_template(
    template_id: uuid.UUID,
    _claims: _Admin,
    repo: _TmplRepo,
) -> dict[str, Any]:
    template = await repo.get(str(template_id))
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return _normalize_template(template)


@router.post("/sessions/templates/{template_id}/generate")
async def generate_session_instances(
    template_id: uuid.UUID,
    payload: GenerateRequest,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> list[dict[str, Any]]:
    template = await template_repo.get(str(template_id))
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    horizon = date.fromisoformat(payload.horizon)
    # Fetch existing dates for idempotency
    existing_dates: set[str] = set()
    if hasattr(instance_repo, "latest_date_for_template"):
        # Collect already-persisted dates for this template
        existing_list = [
            r
            for r in (await instance_repo.list())
            if r.get("template_id") == str(template_id)
        ]
        existing_dates = {r["date"] for r in existing_list}
    instance_data_list = generate_instances(template, horizon, existing_dates)
    results = []
    for data in instance_data_list:
        record = await instance_repo.add(data)
        results.append(_normalize_instance(record))
    await uow.commit()
    return results


# ---------------------------------------------------------------------------
# Session instances
# ---------------------------------------------------------------------------


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_adhoc_session(
    payload: SessionInstanceCreate,
    _claims: _Admin,
    repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    result = await repo.add(payload.model_dump())
    await uow.commit()
    return _normalize_instance(result)


@router.post("/sessions/{instance_id}/cancel")
async def cancel_session_instance(
    instance_id: uuid.UUID,
    _claims: _Admin,
    repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    record = await repo.cancel(str(instance_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session instance not found",
        )
    await uow.commit()
    return _normalize_instance(record)


def _strip_coach_notes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Strip the session-level coach_notes — admin-only, must never reach a
    # non-admin member.
    return [{**r, "coach_notes": None} for r in records]


def _strip_cancelled(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if not r.get("cancelled")]


async def _enrich_with_attendance(
    rows: list[dict[str, Any]],
    attendance_repo: AbstractAttendanceRepository,
    member_id: str,
) -> list[dict[str, Any]]:
    """Enrich session rows with attendance_count and is_checked_in."""
    session_ids = [r["id"] for r in rows]
    if not session_ids:
        return rows

    # Gather attendance for all sessions concurrently via individual calls
    counts: dict[str, int] = {}
    checked_in: set[str] = set()
    for sid in session_ids:
        records = await attendance_repo.list_for_session(sid)
        counts[sid] = len(records)
        if any(r.get("member_id") == member_id for r in records):
            checked_in.add(sid)

    return [
        {
            **r,
            "attendance_count": counts.get(r["id"], 0),
            "is_checked_in": r["id"] in checked_in,
        }
        for r in rows
    ]


@router.get("/sessions")
async def list_upcoming_sessions(
    claims: _Member,
    repo: _InstRepo,
    template_repo: _TmplRepo,
    attendance_repo: _AttendanceRepo,
    uow: _UoW,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> list[dict[str, Any]]:
    is_admin = claims.role == "admin"

    async def _finalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched = await _enrich_with_attendance(rows, attendance_repo, claims.sub)
        normalized = [_normalize_instance(r) for r in enriched]
        if is_admin:
            return normalized
        return _strip_coach_notes(_strip_cancelled(normalized))

    if from_date is not None and to_date is not None:
        if hasattr(repo, "list_in_range"):
            rows = await repo.list_in_range(from_date, to_date)
            return await _finalize(rows)
        return await _finalize(await repo.list_upcoming())

    # Rolling extension: check each template and extend if needed
    if hasattr(repo, "latest_date_for_template"):
        today = date.today()
        horizon = today + timedelta(days=90)
        templates = await template_repo.list()
        new_instances = []
        for tmpl in templates:
            latest = await repo.latest_date_for_template(tmpl["id"])
            if needs_rolling_extension(latest, today):
                # Collect existing dates for idempotency
                all_instances = await repo.list()
                existing_dates = {
                    r["date"]
                    for r in all_instances
                    if r.get("template_id") == tmpl["id"]
                }
                new_data = generate_instances(tmpl, horizon, existing_dates)
                for data in new_data:
                    record = await repo.add(data)
                    new_instances.append(record)
        if new_instances:
            await uow.commit()

    return await _finalize(await repo.list_upcoming())


@router.get("/sessions/{instance_id}")
async def get_session_instance(
    instance_id: uuid.UUID,
    claims: _Member,
    repo: _InstRepo,
) -> dict[str, Any]:
    record = await repo.get(str(instance_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session instance not found",
        )
    result = _normalize_instance(record)
    if claims.role != "admin":
        result["coach_notes"] = None
    return result


@router.put("/sessions/{instance_id}")
async def update_session_instance(
    instance_id: uuid.UUID,
    payload: SessionInstanceUpdate,
    _claims: _Admin,
    repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    # checkin window overrides are nullable-by-design: an explicitly provided
    # None clears the override to "use the live dojo default", so it must
    # survive the generic not-None filter above (which otherwise treats
    # missing-and-None-are-both-untouched for the rest of this payload).
    explicitly_set = payload.model_dump(exclude_unset=True)
    for key in ("checkin_window_before_minutes", "checkin_window_after_minutes"):
        if key in explicitly_set:
            data[key] = explicitly_set[key]
    record = await repo.update(str(instance_id), data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session instance not found",
        )
    await uow.commit()
    return _normalize_instance(record)


@router.patch("/sessions/templates/{template_id}")
async def update_session_template(
    template_id: uuid.UUID,
    payload: SessionTemplateUpdate,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    template = await template_repo.update(str(template_id), data)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    today = date.today()
    horizon = today + timedelta(days=90)
    await instance_repo.delete_future_for_template(str(template_id), today)
    instance_data_list = generate_instances(template, horizon, set())
    for inst_data in instance_data_list:
        await instance_repo.add(inst_data)
    await uow.commit()
    return _normalize_template(template)


@router.delete("/sessions/templates/{template_id}")
async def delete_session_template(
    template_id: uuid.UUID,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    template = await template_repo.deactivate(str(template_id))
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    today = date.today()
    await instance_repo.cancel_future_for_template(str(template_id), today)
    await uow.commit()
    return _normalize_template(template)
