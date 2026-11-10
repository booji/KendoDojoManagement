from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.member_federations.dependencies import get_member_federation_repo
from app.member_federations.repository import (
    AbstractMemberFederationRepository,
    MemberFederationRecord,
)
from app.member_federations.schemas import (
    MemberFederationCreate,
    MemberFederationResponse,
    MemberFederationUpdate,
    compute_renewal_status,
)
from app.members.dependencies import get_member_repo
from app.members.repository import AbstractMemberRepository

router = APIRouter(tags=["member_federations"])

_MfRepo = Annotated[
    AbstractMemberFederationRepository, Depends(get_member_federation_repo)
]
_MemberRepo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[AccountClaims, Depends(REQUIRE_MEMBER)]


def _to_response(record: MemberFederationRecord) -> MemberFederationResponse:
    return MemberFederationResponse(
        id=record.id,
        member_id=record.member_id,
        federation_id=record.federation_id,
        member_number=record.member_number,
        renewal_date=record.renewal_date,
        renewal_status=compute_renewal_status(record.renewal_date),
    )


# ===========================================================================
# Admin endpoints — /members/{member_id}/federations
# ===========================================================================


@router.get("/members/{member_id}/federations")
async def admin_list_member_federations(
    member_id: uuid.UUID,
    _claims: _Admin,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
) -> list[MemberFederationResponse]:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    records = await mf_repo.get_for_member(str(member_id))
    return [_to_response(r) for r in records]


@router.post("/members/{member_id}/federations", status_code=status.HTTP_201_CREATED)
async def admin_add_member_federation(
    member_id: uuid.UUID,
    payload: MemberFederationCreate,
    _claims: _Admin,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
    uow: _UoW,
) -> MemberFederationResponse:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    data = payload.model_dump()
    data["member_id"] = str(member_id)
    record = await mf_repo.add(data)
    await uow.commit()
    return _to_response(record)


@router.put("/members/{member_id}/federations/{mf_id}")
async def admin_update_member_federation(
    member_id: uuid.UUID,
    mf_id: uuid.UUID,
    payload: MemberFederationUpdate,
    _claims: _Admin,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
    uow: _UoW,
) -> MemberFederationResponse:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    existing = await mf_repo.get(str(mf_id))
    if existing is None or existing.member_id != str(member_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
        )
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    record = await mf_repo.update(str(mf_id), data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
        )
    await uow.commit()
    return _to_response(record)


@router.delete(
    "/members/{member_id}/federations/{mf_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def admin_remove_member_federation(
    member_id: uuid.UUID,
    mf_id: uuid.UUID,
    _claims: _Admin,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
    uow: _UoW,
) -> None:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    existing = await mf_repo.get(str(mf_id))
    if existing is None or existing.member_id != str(member_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
        )
    await mf_repo.remove(str(mf_id))
    await uow.commit()


# ===========================================================================
# Self-service endpoints — /accounts/me/federations
# ===========================================================================


async def _get_member_by_user(
    user_id: str, member_repo: AbstractMemberRepository
) -> dict:
    member = await member_repo.get_by_user_id(user_id)
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    return member


@router.get("/accounts/me/federations")
async def me_list_federations(
    claims: _Member,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
) -> list[MemberFederationResponse]:
    member = await _get_member_by_user(claims.sub, member_repo)
    records = await mf_repo.get_for_member(member["id"])
    return [_to_response(r) for r in records]


@router.post("/accounts/me/federations", status_code=status.HTTP_201_CREATED)
async def me_add_federation(
    payload: MemberFederationCreate,
    claims: _Member,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
    uow: _UoW,
) -> MemberFederationResponse:
    member = await _get_member_by_user(claims.sub, member_repo)
    data = payload.model_dump()
    data["member_id"] = member["id"]
    record = await mf_repo.add(data)
    await uow.commit()
    return _to_response(record)


@router.put("/accounts/me/federations/{mf_id}")
async def me_update_federation(
    mf_id: uuid.UUID,
    payload: MemberFederationUpdate,
    claims: _Member,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
    uow: _UoW,
) -> MemberFederationResponse:
    member = await _get_member_by_user(claims.sub, member_repo)
    existing = await mf_repo.get(str(mf_id))
    if existing is None or existing.member_id != member["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
        )
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    record = await mf_repo.update(str(mf_id), data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
        )
    await uow.commit()
    return _to_response(record)


@router.delete(
    "/accounts/me/federations/{mf_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def me_remove_federation(
    mf_id: uuid.UUID,
    claims: _Member,
    member_repo: _MemberRepo,
    mf_repo: _MfRepo,
    uow: _UoW,
) -> None:
    member = await _get_member_by_user(claims.sub, member_repo)
    existing = await mf_repo.get(str(mf_id))
    if existing is None or existing.member_id != member["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
        )
    await mf_repo.remove(str(mf_id))
    await uow.commit()
