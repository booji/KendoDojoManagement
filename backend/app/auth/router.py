from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app import config
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import LoginRequest, RegisterRequest, UserClaims
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
        secure=False,  # set True in prod via config
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


@router.get("/admin-only", response_model=UserClaims)
async def admin_only(
    claims: Annotated[UserClaims, Depends(REQUIRE_ADMIN)],
) -> UserClaims:
    return claims
