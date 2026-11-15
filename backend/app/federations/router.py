from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.federations.dependencies import get_federation_repo
from app.federations.repository import AbstractFederationRepository
from app.federations.schemas import (
    FederationCreate,
    FederationResponse,
    FederationUpdate,
)

router = APIRouter(tags=["federations"])

_Repo = Annotated[AbstractFederationRepository, Depends(get_federation_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[AccountClaims, Depends(REQUIRE_MEMBER)]


def _to_response(record: dict[str, Any]) -> FederationResponse:
    return FederationResponse(
        id=record["id"],
        name=record["name"],
        abbreviation=record.get("abbreviation"),
        iso_code=record.get("iso_code"),
        website=record.get("website"),
        continental_grouping=record.get("continental_grouping"),
        type=record.get("type"),
        is_pinned=record.get("is_pinned", False),
        is_active=record.get("is_active", True),
    )


@router.post("/federations", status_code=status.HTTP_201_CREATED)
async def create_federation(
    payload: FederationCreate,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> FederationResponse:
    data = payload.model_dump()
    record = await repo.add(data)
    await uow.commit()
    return _to_response(record)


@router.get("/federations")
async def list_federations(
    _claims: _Member,
    repo: _Repo,
    type: str | None = None,
    continental_grouping: str | None = None,
    search: str | None = None,
) -> list[FederationResponse]:
    records = await repo.list(
        type=type,
        continental_grouping=continental_grouping,
        search=search,
    )
    return [_to_response(r) for r in records]


@router.get("/federations/{federation_id}")
async def get_federation(
    federation_id: uuid.UUID,
    _claims: _Member,
    repo: _Repo,
) -> FederationResponse:
    record = await repo.get(str(federation_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Federation not found"
        )
    return _to_response(record)


@router.put("/federations/{federation_id}")
async def update_federation(
    federation_id: uuid.UUID,
    payload: FederationUpdate,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> FederationResponse:
    record = await repo.update(str(federation_id), payload.changes())
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Federation not found"
        )
    await uow.commit()
    return _to_response(record)


@router.delete("/federations/{federation_id}")
async def deactivate_federation(
    federation_id: uuid.UUID,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> FederationResponse:
    record = await repo.deactivate(str(federation_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Federation not found"
        )
    await uow.commit()
    return _to_response(record)
