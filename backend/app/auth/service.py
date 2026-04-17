from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.auth.db_models import User
from app.auth.models import LoginRequest, RegisterRequest, TokenResponse, UserClaims
from app.auth.password import hash_password, verify_password
from app.auth.token import encode_token
from app.db.unit_of_work import AbstractUnitOfWork


async def register_user(
    payload: RegisterRequest, uow: AbstractUnitOfWork
) -> UserClaims:
    """UoW is already entered by the FastAPI dependency — do not re-enter.

    The first user to register on a fresh instance is promoted to admin
    automatically (self-hosted single-dojo pattern).
    """
    count_result = await uow.session.execute(select(func.count()).select_from(User))
    is_first_user = count_result.scalar_one() == 0
    role = "admin" if is_first_user else "member"

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=role,
        is_active=True,
    )
    uow.session.add(user)
    try:
        await uow.commit()
    except IntegrityError:
        await uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return UserClaims(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
    )


async def login_user(payload: LoginRequest, uow: AbstractUnitOfWork) -> TokenResponse:
    """UoW is already entered by the FastAPI dependency — do not re-enter."""
    result = await uow.session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    claims = UserClaims(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
    )
    return TokenResponse(access_token=encode_token(claims))
