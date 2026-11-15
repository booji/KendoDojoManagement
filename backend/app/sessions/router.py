from __future__ import annotations

import os
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app import config
from app.attendance.dependencies import get_attendance_repo
from app.attendance.repository import AbstractAttendanceRepository
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_current_member_id
from app.sessions import templates
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from app.sessions.ical import build_ical, feed_url_name
from app.sessions.models import (
    GenerateRequest,
    SegmentCreate,
    SessionInstanceCreate,
    SessionInstanceRead,
    SessionInstanceUpdate,
    SessionTemplateCreate,
    SessionTemplateExtend,
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
from app.settings.dependencies import get_dojo_settings_repo
from app.settings.repository import AbstractDojoSettingsRepository

router = APIRouter(tags=["sessions"])


def checkin_link(session_id: str) -> str:
    """The one check-in link a session has (#191).

    Tokenless, stable and public: it drives POST /sessions/{id}/checkin, which
    authenticates the member and enforces the check-in window, so the link
    itself grants nothing on its own.
    """
    origin = os.getenv("PUBLIC_ORIGIN") or os.getenv(
        "WEBAUTHN_ORIGIN", "http://localhost:5173"
    )
    return f"{origin.rstrip('/')}/checkin/session/{session_id}"


def _normalize_instance(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply SessionInstanceRead defaults and attach the session's check-in link."""
    record = SessionInstanceRead.model_validate(raw).model_dump()
    record["checkin_link"] = checkin_link(record["id"])
    return record


def _normalize_template(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply SessionTemplateRead defaults to fill in any missing optional fields."""
    return SessionTemplateRead.model_validate(raw).model_dump()


_TypeRepo = Annotated[AbstractSessionTypeRepository, Depends(get_session_type_repo)]
_TmplRepo = Annotated[
    AbstractSessionTemplateRepository, Depends(get_session_template_repo)
]
_InstRepo = Annotated[
    AbstractSessionInstanceRepository, Depends(get_session_instance_repo)
]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[AccountClaims, Depends(REQUIRE_MEMBER)]
_AttendanceRepo = Annotated[AbstractAttendanceRepository, Depends(get_attendance_repo)]
_CurrentMemberId = Annotated[str | None, Depends(get_current_member_id)]


async def _require_known_types(
    segments: list[SegmentCreate] | None, type_repo: AbstractSessionTypeRepository
) -> None:
    # Checked here rather than left to the foreign key, whose violation would
    # surface as an unmapped 500 (#586). A 422, not a 404: the unknown id is a
    # reference inside the body, not the resource the path names.
    if not segments:
        return
    known = {t["id"] for t in await type_repo.list()}
    if any(str(tid) not in known for seg in segments for tid in seg.type_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Session type not found",
        )


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


@router.get("/sessions/ical/{name}")
async def get_sessions_ical(
    name: str,
    repo: _InstRepo,
    type_repo: _TypeRepo,
    settings_repo: Annotated[
        AbstractDojoSettingsRepository, Depends(get_dojo_settings_repo)
    ],
) -> Response:
    settings = await settings_repo.get()
    # The URL must end in the current dojo name. Renaming the dojo breaks
    # existing subscriptions on purpose: members re-subscribe, and the URL
    # never names a dojo that no longer exists.
    if name != feed_url_name(settings["dojo_name"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calendar feed not found"
        )
    sessions = await repo.list_upcoming()
    types = {t["id"]: t["name"] for t in await type_repo.list()}
    enriched = [
        {
            **s,
            "segments": _enrich_segments_with_type_names(s.get("segments", []), types),
            "checkin_link": checkin_link(s["id"]),
        }
        for s in sessions
    ]
    content = build_ical(
        enriched, tz_name=config.TIMEZONE, calendar_name=settings["dojo_name"]
    )
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
    instance_repo: _InstRepo,
    type_repo: _TypeRepo,
    uow: _UoW,
) -> dict[str, Any]:
    await _require_known_types(payload.segments, type_repo)
    template = await templates.create(payload.model_dump(), repo, instance_repo)
    await uow.commit()
    return _normalize_template(template)


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
    created = await templates.generate_to_horizon(
        str(template_id),
        date.fromisoformat(payload.horizon),
        template_repo,
        instance_repo,
    )
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    await uow.commit()
    return [_normalize_instance(record) for record in created]


# ---------------------------------------------------------------------------
# Session instances
# ---------------------------------------------------------------------------


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_adhoc_session(
    payload: SessionInstanceCreate,
    _claims: _Admin,
    repo: _InstRepo,
    type_repo: _TypeRepo,
    template_repo: _TmplRepo,
    uow: _UoW,
) -> dict[str, Any]:
    await _require_known_types(payload.segments, type_repo)
    # Same reason, and the same 422, as the types: template_id is a foreign
    # key named in the body (#586).
    if (
        payload.template_id is not None
        and await template_repo.get(str(payload.template_id)) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Template not found",
        )
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


@router.post("/sessions/{instance_id}/reinstate")
async def reinstate_session_instance(
    instance_id: uuid.UUID,
    _claims: _Admin,
    repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    """Undo a Cancellation (#579). A cancelled series stays cancelled: this
    puts back only the one Session."""
    record = await repo.update(str(instance_id), {"cancelled": False})
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
    member_id: str | None,
) -> list[dict[str, Any]]:
    """Enrich session rows with attendance_count and is_checked_in."""
    session_ids = [r["id"] for r in rows]
    if not session_ids:
        return rows

    summary = await attendance_repo.summary_for_sessions(session_ids, member_id)
    return [{**r, **summary[r["id"]]} for r in rows]


@router.get("/sessions")
async def list_upcoming_sessions(
    claims: _Member,
    repo: _InstRepo,
    attendance_repo: _AttendanceRepo,
    current_member_id: _CurrentMemberId,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> list[dict[str, Any]]:
    is_admin = claims.role == "admin"

    async def _finalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # The caller's Member id, not their Account id: attendance is keyed by
        # member however it was recorded (#340).
        enriched = await _enrich_with_attendance(
            rows, attendance_repo, current_member_id
        )
        normalized = [_normalize_instance(r) for r in enriched]
        if is_admin:
            return normalized
        return _strip_coach_notes(_strip_cancelled(normalized))

    if from_date is not None and to_date is not None:
        return await _finalize(await repo.list_in_range(from_date, to_date))

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
    type_repo: _TypeRepo,
    uow: _UoW,
) -> dict[str, Any]:
    await _require_known_types(payload.segments, type_repo)
    record = await repo.update(str(instance_id), payload.changes())
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
    type_repo: _TypeRepo,
    uow: _UoW,
) -> dict[str, Any]:
    await _require_known_types(payload.segments, type_repo)
    template = await templates.reschedule(
        str(template_id), payload.changes(), template_repo, instance_repo
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    await uow.commit()
    return _normalize_template(template)


@router.post("/sessions/templates/{template_id}/extend")
async def extend_session_template(
    template_id: uuid.UUID,
    payload: SessionTemplateExtend,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    try:
        template = await templates.extend(
            str(template_id),
            date.fromisoformat(payload.end_date),
            template_repo,
            instance_repo,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
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
    template = await templates.cancel(str(template_id), template_repo, instance_repo)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    await uow.commit()
    return _normalize_template(template)
