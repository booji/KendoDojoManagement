from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.grades.dependencies import get_grade_repo
from app.grades.models import (
    CurrentGradeResponse,
    Grade,
    GradeHistoryEntry,
    PendingGradeEntry,
    SetGradeRequest,
    SetGradeResponse,
)
from app.grades.repository import AbstractGradeRepository
from app.members.dependencies import get_member_repo
from app.members.repository import AbstractMemberRepository

router = APIRouter(tags=["grades"])

_GradeRepo = Annotated[AbstractGradeRepository, Depends(get_grade_repo)]
_MemberRepo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[AccountClaims, Depends(REQUIRE_MEMBER)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]


def _entry_from_dict(
    d: dict[str, Any], *, include_assigned_by: bool
) -> GradeHistoryEntry:
    return GradeHistoryEntry(
        id=d["id"],
        member_id=d["member_id"],
        grade=d["grade"],
        display_name=d["display_name"],
        promoted_at=d["promoted_at"],
        assigned_by=d["assigned_by"] if include_assigned_by else None,
        status=d["status"],
    )


# ---------------------------------------------------------------------------
# GET /grades/pending — admin only
# ---------------------------------------------------------------------------


@router.get("/grades/pending")
async def list_pending_grades(
    claims: _Admin,
    grade_repo: _GradeRepo,
) -> list[PendingGradeEntry]:
    entries = await grade_repo.list_pending()
    return [PendingGradeEntry(**e) for e in entries]


# ---------------------------------------------------------------------------
# POST /members/{member_id}/grades — admin only
# ---------------------------------------------------------------------------


@router.post("/members/{member_id}/grades", status_code=status.HTTP_201_CREATED)
async def set_member_grade(
    member_id: uuid.UUID,
    body: SetGradeRequest,
    claims: _Admin,
    member_repo: _MemberRepo,
    grade_repo: _GradeRepo,
    uow: _UoW,
) -> SetGradeResponse:
    if body.grade == Grade.MUKYUU:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MUKYUU cannot be assigned",
        )

    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    awarded_at = (body.awarded_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    record = await grade_repo.add_promotion(
        member_id=str(member_id),
        grade=body.grade.value,
        display_name=body.grade.display_name,
        assigned_by=claims.sub,
        promoted_at=awarded_at,
        status="confirmed",
    )
    await uow.commit()
    return SetGradeResponse(
        id=record["id"],
        member_id=record["member_id"],
        grade=record["grade"],
        display_name=record["display_name"],
        awarded_at=record["promoted_at"],
        assigned_by=record["assigned_by"],
        status=record["status"],
    )


# ---------------------------------------------------------------------------
# POST /members/{member_id}/grades/propose — member only (own record)
# ---------------------------------------------------------------------------


@router.post("/members/{member_id}/grades/propose", status_code=status.HTTP_201_CREATED)
async def propose_member_grade(
    member_id: uuid.UUID,
    body: SetGradeRequest,
    claims: _Member,
    member_repo: _MemberRepo,
    grade_repo: _GradeRepo,
    uow: _UoW,
) -> SetGradeResponse:
    if claims.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot use the member propose endpoint",
        )

    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    if member.get("user_id") != claims.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only propose a grade for your own record",
        )

    if body.grade == Grade.MUKYUU:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MUKYUU cannot be proposed",
        )

    proposed_at = (body.awarded_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    record = await grade_repo.add_promotion(
        member_id=str(member_id),
        grade=body.grade.value,
        display_name=body.grade.display_name,
        assigned_by=None,
        promoted_at=proposed_at,
        status="pending",
    )
    await uow.commit()
    return SetGradeResponse(
        id=record["id"],
        member_id=record["member_id"],
        grade=record["grade"],
        display_name=record["display_name"],
        awarded_at=record["promoted_at"],
        assigned_by=record["assigned_by"],
        status=record["status"],
    )


# ---------------------------------------------------------------------------
# GET /members/{member_id}/grades/current — member (own) or admin (any)
# ---------------------------------------------------------------------------


@router.get("/members/{member_id}/grades/current")
async def get_current_grade(
    member_id: uuid.UUID,
    claims: _Member,
    member_repo: _MemberRepo,
    grade_repo: _GradeRepo,
) -> CurrentGradeResponse:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    if claims.role != "admin" and member.get("user_id") != claims.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    history = await grade_repo.get_history(str(member_id))
    confirmed = [e for e in history if e.get("status") == "confirmed"]
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No grade history found"
        )

    latest = max(confirmed, key=lambda e: e["promoted_at"])
    return CurrentGradeResponse(
        grade=latest["grade"],
        display_name=latest["display_name"],
        awarded_at=latest["promoted_at"],
    )


# ---------------------------------------------------------------------------
# GET /members/{member_id}/grades — member (own) or admin (any)
# ---------------------------------------------------------------------------


@router.get("/members/{member_id}/grades", response_model_exclude_none=True)
async def get_grade_history(
    member_id: uuid.UUID,
    claims: _Member,
    member_repo: _MemberRepo,
    grade_repo: _GradeRepo,
) -> list[GradeHistoryEntry]:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    if claims.role != "admin":
        if member.get("user_id") != claims.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )

    is_admin = claims.role == "admin"
    history = await grade_repo.get_history(str(member_id))
    return [_entry_from_dict(e, include_assigned_by=is_admin) for e in history]


# ---------------------------------------------------------------------------
# POST /members/{member_id}/grades/{entry_id}/approve — admin only
# ---------------------------------------------------------------------------


@router.post("/members/{member_id}/grades/{entry_id}/approve")
async def approve_grade_entry(
    member_id: uuid.UUID,
    entry_id: uuid.UUID,
    claims: _Admin,
    grade_repo: _GradeRepo,
    uow: _UoW,
) -> GradeHistoryEntry:
    try:
        record = await grade_repo.approve_entry(
            str(member_id), str(entry_id), claims.sub
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Grade entry not found"
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Entry is not pending"
        )
    await uow.commit()
    return _entry_from_dict(record, include_assigned_by=True)


# ---------------------------------------------------------------------------
# DELETE /members/{member_id}/grades/{entry_id} — admin only
# ---------------------------------------------------------------------------


@router.delete(
    "/members/{member_id}/grades/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_grade_entry(
    member_id: uuid.UUID,
    entry_id: uuid.UUID,
    claims: _Admin,
    grade_repo: _GradeRepo,
    uow: _UoW,
) -> None:
    try:
        await grade_repo.delete_entry(str(member_id), str(entry_id))
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Grade entry not found"
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending entries may be deleted",
        )
    await uow.commit()
