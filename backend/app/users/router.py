from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_member_repo
from app.members.models import MemberResponse, SelfUpdateMemberRequest
from app.members.repository import AbstractMemberRepository
from app.members.router import _to_response

router = APIRouter(prefix="/users", tags=["users"])

_Repo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]


# ---------------------------------------------------------------------------
# GET /users/me/member — returns the Member record linked to the caller
# ---------------------------------------------------------------------------


@router.get("/me/member")
async def get_my_member(
    claims: _Member,
    repo: _Repo,
) -> MemberResponse:
    record = await repo.get_by_user_id(claims.sub)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No member record linked to this account",
        )
    return _to_response(record)


# ---------------------------------------------------------------------------
# PUT /users/me/member — partial update or first-save onboarding
# ---------------------------------------------------------------------------


@router.put("/me/member")
async def put_my_member(
    payload: SelfUpdateMemberRequest,
    claims: _Member,
    repo: _Repo,
    uow: _UoW,
) -> MemberResponse:
    data: dict[str, Any] = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }
    if "dob" in data and hasattr(data["dob"], "isoformat"):
        data["dob"] = data["dob"].isoformat()

    record = await repo.get_by_user_id(claims.sub)

    if record is None:
        # First-save onboarding — create a new Member record
        new_data: dict[str, Any] = {
            "email": claims.email,
            "full_name": data.get("full_name", ""),
            # Placeholder DOB — user should update this in Settings
            "dob": data.get("dob", "1900-01-01"),
            "join_date": date.today().isoformat(),
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
            "emergency_contact_name": data.get("emergency_contact_name"),
            "emergency_contact_phone": data.get("emergency_contact_phone"),
            "federation_number": data.get("federation_number"),
            "parental_consent_obtained": False,
            "user_id": claims.sub,
        }
        try:
            record = await repo.add(new_data)
            await uow.commit()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A member record is already linked to this account",
            )
        return _to_response(record)

    record = await repo.update(record["id"], data)
    await uow.commit()
    return _to_response(record)  # type: ignore[arg-type]
