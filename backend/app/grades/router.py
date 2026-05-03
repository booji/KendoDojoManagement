from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.grades.dependencies import get_grade_repo
from app.grades.models import Grade, GradeHistoryEntry, PromoteResponse
from app.grades.repository import AbstractGradeRepository
from app.members.dependencies import get_member_repo
from app.members.repository import AbstractMemberRepository

router = APIRouter(tags=["grades"])

_GradeRepo = Annotated[AbstractGradeRepository, Depends(get_grade_repo)]
_MemberRepo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]

_GRADES = list(Grade)


def _next_grade(current: str | None) -> Grade | None:
    """Return the next grade after current, or None if already at max."""
    if current is None:
        # No grade yet — first promotion goes to ROKKYUU (index 1)
        return _GRADES[1]
    try:
        idx = _GRADES.index(Grade(current))
    except ValueError:
        return _GRADES[1]
    if idx >= len(_GRADES) - 1:
        return None
    return _GRADES[idx + 1]


def _entry_from_dict(d: dict[str, Any]) -> GradeHistoryEntry:
    return GradeHistoryEntry(
        id=d["id"],
        member_id=d["member_id"],
        grade=d["grade"],
        display_name=d["display_name"],
        promoted_at=d["promoted_at"],
        awarded_by=d["awarded_by"],
    )


# ---------------------------------------------------------------------------
# POST /members/{member_id}/promote — admin only
# ---------------------------------------------------------------------------


@router.post("/members/{member_id}/promote")
async def promote_member(
    member_id: uuid.UUID,
    claims: _Admin,
    member_repo: _MemberRepo,
    grade_repo: _GradeRepo,
) -> PromoteResponse:
    member = await member_repo.get(str(member_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    current = await grade_repo.get_current_grade(str(member_id))
    next_grade = _next_grade(current)

    if next_grade is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot promote beyond Hachidan",
        )

    promoted_at = datetime.now(UTC).isoformat()
    record = await grade_repo.add_promotion(
        member_id=str(member_id),
        grade=next_grade.value,
        display_name=next_grade.display_name,
        awarded_by=claims.sub,
        promoted_at=promoted_at,
    )
    return PromoteResponse(**record)


# ---------------------------------------------------------------------------
# GET /members/{member_id}/grades — member (own) or admin (any)
# ---------------------------------------------------------------------------


@router.get("/members/{member_id}/grades")
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

    history = await grade_repo.get_history(str(member_id))
    return [_entry_from_dict(e) for e in history]
