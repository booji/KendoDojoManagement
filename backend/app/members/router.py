from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_member_repo
from app.members.models import CreateMemberRequest, MemberResponse, UpdateMemberRequest
from app.members.repository import AbstractMemberRepository

router = APIRouter(tags=["members"])

_Repo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]


def _compute_is_minor(dob: str | None) -> bool:
    """Return True if person is under 18 today. Returns False when dob is None."""
    if not dob:
        return False
    birth = date.fromisoformat(dob) if isinstance(dob, str) else dob
    today = date.today()
    age = (
        today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    )
    return age < 18


def _to_response(record: dict[str, Any]) -> MemberResponse:
    dob = record.get("dob")
    return MemberResponse(
        id=record["id"],
        email=record["email"],
        first_name=record["first_name"],
        surname=record["surname"],
        display_name=record.get("display_name"),
        dob=dob,
        join_date=str(record.get("join_date", "")),
        membership_status=record["membership_status"],
        is_coach=record["is_coach"],
        is_first_aider=record["is_first_aider"],
        emergency_contact_name=record.get("emergency_contact_name"),
        emergency_contact_phone=record.get("emergency_contact_phone"),
        is_minor=_compute_is_minor(dob),
    )


# ---------------------------------------------------------------------------
# POST /members — admin only
# ---------------------------------------------------------------------------


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: CreateMemberRequest,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> MemberResponse:
    data = payload.model_dump()
    # Convert date fields to ISO strings for storage
    if data["dob"] is not None:
        data["dob"] = data["dob"].isoformat()
    data["join_date"] = data["join_date"].isoformat()
    try:
        record = await repo.add(data)
        await uow.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _to_response(record)


# ---------------------------------------------------------------------------
# GET /members — admin only, with optional status and search filters
# ---------------------------------------------------------------------------


@router.get("/members")
async def list_members(
    _claims: _Admin,
    repo: _Repo,
    status: str | None = None,
    search: str | None = None,
) -> list[MemberResponse]:
    records = await repo.list(status=status, search=search)
    return [_to_response(r) for r in records]


# ---------------------------------------------------------------------------
# GET /members/{id} — admin sees any; member sees own only
# ---------------------------------------------------------------------------


@router.get("/members/{member_id}")
async def get_member(
    member_id: uuid.UUID,
    claims: _Member,
    repo: _Repo,
) -> MemberResponse:
    record = await repo.get(str(member_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    # Admins may see any member; non-admins may only see their own profile
    if claims.role != "admin":
        user_id = record.get("user_id")
        if user_id != claims.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
    return _to_response(record)


# ---------------------------------------------------------------------------
# PUT /members/{id} — admin only, partial update
# ---------------------------------------------------------------------------


@router.put("/members/{member_id}")
async def update_member(
    member_id: uuid.UUID,
    payload: UpdateMemberRequest,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> MemberResponse:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "dob" in data and hasattr(data["dob"], "isoformat"):
        data["dob"] = data["dob"].isoformat()
    if "join_date" in data and hasattr(data["join_date"], "isoformat"):
        data["join_date"] = data["join_date"].isoformat()
    record = await repo.update(str(member_id), data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    await uow.commit()
    return _to_response(record)


