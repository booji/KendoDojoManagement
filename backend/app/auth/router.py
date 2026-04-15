import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import update

from app import config
from app.auth.db_models import User
from app.auth.dependencies import get_passkey_repo, get_recovery_repo
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import (
    LoginRequest,
    PasskeyBeginRequest,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    RegisterRequest,
    ThemeUpdate,
    UserClaims,
)
from app.auth.passkey_repository import AbstractPasskeyRepository
from app.auth.passkey_service import (
    login_passkey_begin,
    login_passkey_complete,
    register_passkey_begin,
    register_passkey_complete,
)
from app.auth.recovery_repository import AbstractRecoveryRepository
from app.auth.recovery_service import generate_recovery_codes, hash_codes
from app.auth.service import login_user, register_user
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register/password", response_model=UserClaims, status_code=201)
async def register_password(
    payload: RegisterRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> UserClaims:
    return await register_user(payload, uow)


@router.post("/login/password", status_code=200)
async def login_password(
    payload: LoginRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    token_response = await login_user(payload, uow)
    response.set_cookie(
        key="access_token",
        value=token_response.access_token,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE,
        max_age=60 * int(config.JWT_EXPIRE_MINUTES),
    )
    return {"detail": "logged in"}


@router.post("/logout", status_code=200)
async def logout(response: Response) -> dict:
    response.delete_cookie("access_token")
    return {"detail": "logged out"}


@router.get("/me", response_model=UserClaims)
async def me(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
) -> UserClaims:
    return claims


@router.patch("/me/theme", response_model=UserClaims)
async def update_theme(
    payload: ThemeUpdate,
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> UserClaims:
    await uow.session.execute(
        update(User).where(User.id == claims.sub).values(theme=payload.theme)
    )
    await uow.commit()
    return UserClaims(
        sub=claims.sub,
        email=claims.email,
        role=claims.role,
        is_active=claims.is_active,
        theme=payload.theme,
    )


@router.get("/admin-only", response_model=UserClaims)
async def admin_only(
    claims: Annotated[UserClaims, Depends(REQUIRE_ADMIN)],
) -> UserClaims:
    return claims


@router.post("/register/passkey/begin")
async def passkey_register_begin(
    payload: PasskeyBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    return await register_passkey_begin(payload.email, uow)


@router.post("/register/passkey/complete", status_code=201)
async def passkey_register_complete(
    payload: PasskeyRegisterCompleteRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> UserClaims:
    return await register_passkey_complete(payload, uow)


@router.post("/login/passkey/begin")
async def passkey_login_begin(
    payload: PasskeyBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    return await login_passkey_begin(payload.email, uow)


@router.post("/login/passkey/complete")
async def passkey_login_complete(
    payload: PasskeyLoginCompleteRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    token_response = await login_passkey_complete(payload, uow)
    response.set_cookie(
        key="access_token",
        value=token_response.access_token,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE,
        max_age=60 * int(config.JWT_EXPIRE_MINUTES),
    )
    return {"detail": "logged in"}


class _LabelUpdate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)


def _passkey_to_response(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "label": record["label"],
        "aaguid": record.get("aaguid"),
        "created_at": record["created_at"],
        "last_used_at": record.get("last_used_at"),
    }


@router.get("/passkeys")
async def list_passkeys(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
) -> list[dict[str, Any]]:
    records = await repo.list_for_user(claims.sub)
    return [_passkey_to_response(r) for r in records]


@router.patch("/passkeys/{passkey_id}")
async def update_passkey_label(
    passkey_id: str,
    payload: _LabelUpdate,
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
) -> dict[str, Any]:
    record = await repo.get(passkey_id)
    if record is None or record["user_id"] != claims.sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updated = await repo.update_label(passkey_id, claims.sub, payload.label)
    return _passkey_to_response(updated)  # type: ignore[arg-type]


@router.delete("/passkeys/{passkey_id}", status_code=204)
async def delete_passkey(
    passkey_id: str,
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
) -> None:
    record = await repo.get(passkey_id)
    if record is None or record["user_id"] != claims.sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    count = await repo.count_for_user(claims.sub)
    if count <= 1:
        unused = await recovery_repo.count_unused(claims.sub)
        if unused == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your only passkey without recovery codes",
            )
    await repo.delete(passkey_id, claims.sub)


@router.post("/recovery/codes/generate", status_code=200)
async def generate_codes(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    if await recovery_repo.has_active_set(claims.sub):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery codes already exist. Use regenerate to replace them.",
        )
    codes = generate_recovery_codes()
    hashes = hash_codes(codes)
    set_id = str(uuid.uuid4())
    await recovery_repo.create_codes(claims.sub, hashes, set_id)
    await uow.commit()
    return {"codes": codes}


@router.post("/recovery/codes/regenerate", status_code=200)
async def regenerate_codes(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    await recovery_repo.invalidate_all(claims.sub)
    codes = generate_recovery_codes()
    hashes = hash_codes(codes)
    set_id = str(uuid.uuid4())
    await recovery_repo.create_codes(claims.sub, hashes, set_id)
    await uow.commit()
    return {"codes": codes}


@router.get("/recovery/codes/status", status_code=200)
async def recovery_codes_status(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
) -> dict[str, Any]:
    unused_count = await recovery_repo.count_unused(claims.sub)
    has_set = await recovery_repo.has_active_set(claims.sub)
    return {"unused_count": unused_count, "has_set": has_set}
