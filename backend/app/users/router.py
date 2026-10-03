from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.session_cookie import set_theme_cookie
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
# PUT /users/me/member — partial update, including completing onboarding
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
        # Every Account belongs to a Member (#432) -- the first Admin's is
        # created at the setup claim, everyone else's before they register --
        # so onboarding completes an existing record, never creates one.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No member record linked to this account",
        )

    # The optional PII fields are nullable-by-design: an explicitly provided
    # None clears the stored value, so it must survive the generic not-None
    # filter above (which otherwise treats missing and None alike — the
    # correct reading for first_name/surname, required-by-domain here).
    explicitly_set = payload.model_dump(exclude_unset=True)
    for key in _CLEARABLE_FIELDS:
        if key in explicitly_set:
            data[key] = explicitly_set[key]
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
    response: Response,
) -> _PreferencesResponse:
    theme = await repo.get_theme(claims.sub) or "system"
    # Seed the readable cookie so the next document load resolves this theme
    # before first paint rather than flashing the OS default (#324).
    set_theme_cookie(response, theme)
    return _PreferencesResponse(theme=theme)


# ---------------------------------------------------------------------------
# PUT /users/me/preferences — saves preferences and returns them
# ---------------------------------------------------------------------------


@router.put("/me/preferences")
async def put_my_preferences(
    payload: _PreferencesUpdate,
    claims: _Member,
    repo: _PrefsRepo,
    uow: _UoW,
    response: Response,
) -> _PreferencesResponse:
    theme = await repo.set_theme(claims.sub, payload.theme)
    await uow.commit()
    set_theme_cookie(response, theme)
    return _PreferencesResponse(theme=theme)
