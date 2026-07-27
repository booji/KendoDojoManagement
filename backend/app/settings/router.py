from __future__ import annotations

import os
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.settings.branding import project_branding
from app.settings.dependencies import get_dojo_settings_repo
from app.settings.repository import AbstractDojoSettingsRepository

router = APIRouter(prefix="/settings", tags=["settings"])

_SettingsRepo = Annotated[
    AbstractDojoSettingsRepository, Depends(get_dojo_settings_repo)
]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]

_STATIC_DIR = os.environ.get("STATIC_DIR", "/tmp/static/logos")
_STATIC_BACKGROUNDS_DIR = os.environ.get(
    "STATIC_BACKGROUNDS_DIR",
    os.path.join(os.path.dirname(_STATIC_DIR.rstrip("/")), "backgrounds"),
)
_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
_MAX_BACKGROUND_BYTES = 5 * 1024 * 1024  # 5 MB
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


_MAX_CHECKIN_WINDOW_MINUTES = 1440


class DojoSettingsUpdate(BaseModel):
    dojo_name: str | None = None
    primary_colour: str | None = None
    checkin_window_before_minutes: int | None = None
    checkin_window_after_minutes: int | None = None
    background_image_url: str | None = None
    login_show_background: bool | None = None
    login_show_logo: bool | None = None
    login_show_name: bool | None = None

    @field_validator("dojo_name")
    @classmethod
    def name_max_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 255:
            raise ValueError("dojo_name must be 255 characters or fewer")
        return v

    @field_validator("primary_colour")
    @classmethod
    def colour_format(cls, v: str | None) -> str | None:
        if v is not None and not _HEX_RE.match(v):
            raise ValueError("primary_colour must be a 6-digit hex string e.g. #1D4ED8")
        return v

    @field_validator("checkin_window_before_minutes", "checkin_window_after_minutes")
    @classmethod
    def checkin_window_minutes_range(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= _MAX_CHECKIN_WINDOW_MINUTES):
            raise ValueError(
                f"must be between 0 and {_MAX_CHECKIN_WINDOW_MINUTES} minutes"
            )
        return v


@router.get("/dojo")
async def get_dojo_settings(claims: _Member, repo: _SettingsRepo) -> dict[str, Any]:
    """Authenticated endpoint — returns dojo name, logo URL, and primary colour."""
    settings = await repo.get()
    return {
        "dojo_name": settings["dojo_name"],
        "logo_url": settings["logo_url"],
        "primary_colour": settings["primary_colour"],
        "checkin_window_before_minutes": settings["checkin_window_before_minutes"],
        "checkin_window_after_minutes": settings["checkin_window_after_minutes"],
        "background_image_url": settings["background_image_url"],
        "login_show_background": settings["login_show_background"],
        "login_show_logo": settings["login_show_logo"],
        "login_show_name": settings["login_show_name"],
    }


@router.put("/dojo")
async def update_dojo_settings(
    payload: DojoSettingsUpdate,
    claims: _Admin,
    repo: _SettingsRepo,
    uow: _UoW,
) -> dict[str, Any]:
    """Admin-only — update dojo name and/or primary colour."""
    # Any valid hex is admissible: the frontend treats primary_colour as a brand
    # *hue* and derives per-theme AA-legible --primary shades from it (issue
    # #223), so the colour itself no longer has to clear contrast against a
    # single background. Format is still enforced by the field validator.
    fields_set = payload.model_fields_set
    data: dict[str, Any] = {}
    for field in (
        "dojo_name",
        "primary_colour",
        "checkin_window_before_minutes",
        "checkin_window_after_minutes",
        "background_image_url",
        "login_show_background",
        "login_show_logo",
        "login_show_name",
    ):
        if field in fields_set:
            data[field] = getattr(payload, field)
    settings = await repo.update(data)
    await uow.commit()
    return {
        "dojo_name": settings["dojo_name"],
        "logo_url": settings["logo_url"],
        "primary_colour": settings["primary_colour"],
        "checkin_window_before_minutes": settings["checkin_window_before_minutes"],
        "checkin_window_after_minutes": settings["checkin_window_after_minutes"],
        "background_image_url": settings["background_image_url"],
        "login_show_background": settings["login_show_background"],
        "login_show_logo": settings["login_show_logo"],
        "login_show_name": settings["login_show_name"],
    }


@router.get("/branding")
async def get_branding(repo: _SettingsRepo) -> dict[str, Any]:
    """Public, unauthenticated — returns the gated login-screen branding view."""
    settings = await repo.get()
    return project_branding(settings)


@router.post("/logo")
async def upload_logo(
    claims: _Admin,
    repo: _SettingsRepo,
    uow: _UoW,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """Admin-only — upload a dojo logo image."""
    # Validate MIME type
    if file.content_type not in _ALLOWED_MIME:
        allowed = ", ".join(sorted(_ALLOWED_MIME))
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: {allowed}",
        )
    ext = os.path.splitext(file.filename or "logo.png")[1].lower() or ".png"
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported extension. Allowed: {', '.join(sorted(_ALLOWED_EXT))}",
        )
    # Read and enforce size limit
    contents = await file.read()
    if len(contents) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=422, detail="Logo must be 2 MB or smaller")

    os.makedirs(_STATIC_DIR, exist_ok=True)
    filename = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(_STATIC_DIR, filename)
    with open(dest, "wb") as fh:
        fh.write(contents)
    logo_url = f"/static/logos/{filename}"
    await repo.update({"logo_url": logo_url})
    await uow.commit()
    return {"logo_url": logo_url}


@router.post("/background")
async def upload_background(
    claims: _Admin,
    repo: _SettingsRepo,
    uow: _UoW,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """Admin-only — upload a login-screen background image."""
    if file.content_type not in _ALLOWED_MIME:
        allowed = ", ".join(sorted(_ALLOWED_MIME))
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: {allowed}",
        )
    ext = os.path.splitext(file.filename or "background.png")[1].lower() or ".png"
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported extension. Allowed: {', '.join(sorted(_ALLOWED_EXT))}",
        )
    contents = await file.read()
    if len(contents) > _MAX_BACKGROUND_BYTES:
        raise HTTPException(
            status_code=422, detail="Background must be 5 MB or smaller"
        )

    os.makedirs(_STATIC_BACKGROUNDS_DIR, exist_ok=True)
    filename = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(_STATIC_BACKGROUNDS_DIR, filename)
    with open(dest, "wb") as fh:
        fh.write(contents)
    background_image_url = f"/static/backgrounds/{filename}"
    await repo.update({"background_image_url": background_image_url})
    await uow.commit()
    return {"background_image_url": background_image_url}
