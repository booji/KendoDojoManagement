from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from app.sessions.models import (
    GenerateRequest,
    SessionInstanceCreate,
    SessionInstanceRead,
    SessionInstanceUpdate,
    SessionTemplateCreate,
    SessionTemplateUpdate,
    SessionTypeCreate,
)
from app.sessions.repository import (
    AbstractSessionInstanceRepository,
    AbstractSessionTemplateRepository,
    AbstractSessionTypeRepository,
)
from app.sessions.service import generate_instances, needs_rolling_extension

router = APIRouter(tags=["sessions"])


def _normalize_instance(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply SessionInstanceRead defaults to fill in any missing optional fields."""
    return SessionInstanceRead.model_validate(raw).model_dump()

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


# ---------------------------------------------------------------------------
# Session types
# ---------------------------------------------------------------------------


@router.get("/session-types")
async def list_session_types(repo: _TypeRepo) -> list[dict[str, Any]]:
    return await repo.list()


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
    return result


@router.get("/sessions/templates/{template_id}")
async def get_session_template(
    template_id: str,
    _claims: _Admin,
    repo: _TmplRepo,
) -> dict[str, Any]:
    template = await repo.get(template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return template


@router.post("/sessions/templates/{template_id}/generate")
async def generate_session_instances(
    template_id: str,
    payload: GenerateRequest,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> list[dict[str, Any]]:
    template = await template_repo.get(template_id)
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
            if r.get("template_id") == template_id
        ]
        existing_dates = {r["date"] for r in existing_list}
    instance_data_list = generate_instances(template, horizon, existing_dates)
    results = []
    for data in instance_data_list:
        record = await instance_repo.add(data)
        results.append(record)
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
    instance_id: str,
    _claims: _Admin,
    repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    record = await repo.cancel(instance_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session instance not found",
        )
    await uow.commit()
    return _normalize_instance(record)


def _strip_coach_notes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "coach_notes": None} for r in records]


def _strip_cancelled(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if not r.get("cancelled")]


@router.get("/sessions")
async def list_upcoming_sessions(
    claims: _Member,
    repo: _InstRepo,
    template_repo: _TmplRepo,
    uow: _UoW,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> list[dict[str, Any]]:
    is_admin = claims.role == "admin"

    def _finalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = [_normalize_instance(r) for r in rows]
        if is_admin:
            return normalized
        return _strip_coach_notes(_strip_cancelled(normalized))

    if from_date is not None and to_date is not None:
        if hasattr(repo, "list_in_range"):
            rows = await repo.list_in_range(from_date, to_date)
            return _finalize(rows)
        return _finalize(await repo.list_upcoming())

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

    return _finalize(await repo.list_upcoming())


@router.get("/sessions/{instance_id}")
async def get_session_instance(
    instance_id: str,
    claims: _Member,
    repo: _InstRepo,
) -> dict[str, Any]:
    record = await repo.get(instance_id)
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
    instance_id: str,
    payload: SessionInstanceUpdate,
    _claims: _Admin,
    repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    record = await repo.update(instance_id, data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session instance not found",
        )
    await uow.commit()
    return _normalize_instance(record)


@router.patch("/sessions/templates/{template_id}")
async def update_session_template(
    template_id: str,
    payload: SessionTemplateUpdate,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    template = await template_repo.update(template_id, data)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    today = date.today()
    horizon = today + timedelta(days=90)
    await instance_repo.delete_future_for_template(template_id, today)
    instance_data_list = generate_instances(template, horizon, set())
    for inst_data in instance_data_list:
        await instance_repo.add(inst_data)
    await uow.commit()
    return template


@router.delete("/sessions/templates/{template_id}")
async def delete_session_template(
    template_id: str,
    _claims: _Admin,
    template_repo: _TmplRepo,
    instance_repo: _InstRepo,
    uow: _UoW,
) -> dict[str, Any]:
    template = await template_repo.deactivate(template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    today = date.today()
    await instance_repo.cancel_future_for_template(template_id, today)
    await uow.commit()
    return template
