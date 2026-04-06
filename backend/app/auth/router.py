from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import update

from app import config
from app.auth.db_models import User
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
from app.auth.passkey_service import (
    login_passkey_begin,
    login_passkey_complete,
    register_passkey_begin,
    register_passkey_complete,
)
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
