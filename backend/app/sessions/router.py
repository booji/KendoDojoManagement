from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

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
    SessionTemplateCreate,
    SessionTypeCreate,
)
from app.sessions.repository import (
    AbstractSessionInstanceRepository,
    AbstractSessionTemplateRepository,
    AbstractSessionTypeRepository,
)
from app.sessions.service import generate_instances

router = APIRouter(tags=["sessions"])

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
    instance_data_list = generate_instances(template, horizon)
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
    return result


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
    return record


@router.get("/sessions/{instance_id}")
async def get_session_instance(
    instance_id: str,
    _claims: _Member,
    repo: _InstRepo,
) -> dict[str, Any]:
    record = await repo.get(instance_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session instance not found",
        )
    return record


@router.get("/sessions")
async def list_upcoming_sessions(
    _claims: _Member,
    repo: _InstRepo,
) -> list[dict[str, Any]]:
    return await repo.list_upcoming()
