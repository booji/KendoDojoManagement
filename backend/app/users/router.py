from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_member_repo
from app.members.models import MemberResponse, SelfUpdateMemberRequest
from app.members.repository import AbstractMemberRepository
from app.members.router import _to_response
from app.users.dependencies import get_user_prefs_repo
from app.users.preferences_repository import AbstractUserPrefsRepo

router = APIRouter(prefix="/users", tags=["users"])

# Self-service fields a member may clear on their own record by sending an
# explicit null. first_name and surname are required-by-domain on this route,
# so a null there means "leave alone" rather than "wipe" — mirrors
# app.members.router._CLEARABLE_FIELDS for the admin-facing update route.
_CLEARABLE_FIELDS = (
    "display_name",
    "dob",
    "emergency_contact_name",
    "emergency_contact_phone",
)

_Repo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]
_PrefsRepo = Annotated[AbstractUserPrefsRepo, Depends(get_user_prefs_repo)]


class _PreferencesResponse(BaseModel):
    theme: Literal["light", "dark", "system"]


class _PreferencesUpdate(BaseModel):
    theme: Literal["light", "dark", "system"]


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

    record = await repo.get_by_user_id(claims.sub)

    if record is None:
        # First-save onboarding — all required fields must be present
        missing: list[str] = []
        if not data.get("first_name"):
            missing.append("first_name")
        if not data.get("surname"):
            missing.append("surname")
        if data.get("dob") is None:
            missing.append("dob")
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing required fields for first save: {', '.join(missing)}",
            )
        dob = data.get("dob")
        # Create a new Member record
        new_data: dict[str, Any] = {
            "email": claims.email,
            "first_name": data.get("first_name", ""),
            "surname": data.get("surname", ""),
            "display_name": data.get("display_name"),
            "dob": dob.isoformat() if hasattr(dob, "isoformat") else dob,
            "join_date": date.today().isoformat(),
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
            "emergency_contact_name": data.get("emergency_contact_name"),
            "emergency_contact_phone": data.get("emergency_contact_phone"),
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

    # The optional PII fields are nullable-by-design: an explicitly provided
    # None clears the stored value, so it must survive the generic not-None
    # filter above (which otherwise treats missing and None alike — the
    # correct reading for first_name/surname, required-by-domain here).
    explicitly_set = payload.model_dump(exclude_unset=True)
    for key in _CLEARABLE_FIELDS:
        if key in explicitly_set:
            data[key] = explicitly_set[key]
    if "dob" in data and hasattr(data["dob"], "isoformat"):
        data["dob"] = data["dob"].isoformat()

    record = await repo.update(record["id"], data)
    await uow.commit()
    return _to_response(record)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GET /users/me/preferences — returns caller's saved preferences
# ---------------------------------------------------------------------------


@router.get("/me/preferences")
async def get_my_preferences(
    claims: _Member,
    repo: _PrefsRepo,
) -> _PreferencesResponse:
    theme = await repo.get_theme(claims.sub)
    return _PreferencesResponse(theme=theme or "system")


# ---------------------------------------------------------------------------
# PUT /users/me/preferences — saves preferences and returns them
# ---------------------------------------------------------------------------


@router.put("/me/preferences")
async def put_my_preferences(
    payload: _PreferencesUpdate,
    claims: _Member,
    repo: _PrefsRepo,
    uow: _UoW,
) -> _PreferencesResponse:
    theme = await repo.set_theme(claims.sub, payload.theme)
    await uow.commit()
    return _PreferencesResponse(theme=theme)
