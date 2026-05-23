"""First-run setup router (issue #38).

Exposes /setup, /setup/passkey/begin, and /setup/passkey/complete.

All three endpoints share the same guard: _has_registered_user().  A "registered
user" is one who has at least one PasskeyCredential row.

Using this definition instead of a raw user-count means:
- Phantom users created by an abandoned begin ceremony (no credentials yet) do
  NOT block a legitimate first-run setup.
- Concurrent begin calls both create phantom rows, but neither blocks the other's
  complete call — the first to complete creates a PasskeyCredential, which causes
  the second complete call to see a registered user and return 404.
- The guard is identical for GET, begin, and complete — no fragile asymmetry.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select

from app import config
from app.auth.db_models import PasskeyCredential, User
from app.auth.models import (
    PasskeyBeginRequest,
    PasskeyRegisterCompleteRequest,
    UserClaims,
)
from app.auth.passkey_service import register_passkey_begin, register_passkey_complete
from app.auth.token import encode_token
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow

router = APIRouter(prefix="/setup", tags=["setup"])

_ALREADY_DONE = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Setup already completed",
)


async def _has_registered_user(uow: AbstractUnitOfWork) -> bool:
    """Return True if any fully-registered user exists.

    A "registered user" is one who has at least one PasskeyCredential row.
    Phantom users from abandoned passkey ceremonies have no credentials, so
    they do not count as registered.
    """
    passkey_count = await uow.session.execute(
        select(func.count()).select_from(PasskeyCredential)
    )
    return passkey_count.scalar_one() > 0


@router.get("")
async def get_setup(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    """Return 200 when instance is unconfigured, 404 otherwise."""
    if await _has_registered_user(uow):
        raise _ALREADY_DONE
    return {"detail": "Setup available"}


@router.post("/passkey/begin")
async def setup_passkey_begin(
    payload: PasskeyBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    """Begin passkey registration for the first admin user."""
    if await _has_registered_user(uow):
        raise _ALREADY_DONE
    return await register_passkey_begin(payload.email, uow)


@router.post("/passkey/complete", status_code=201)
async def setup_passkey_complete(
    payload: PasskeyRegisterCompleteRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> UserClaims:
    """Complete passkey registration, promote user to admin, set cookie."""
    if await _has_registered_user(uow):
        raise _ALREADY_DONE

    claims = await register_passkey_complete(payload, uow)

    # Guarantee the setup user is admin in both DB and JWT.
    # _get_or_create_user already sets role="admin" for the first user, but we
    # explicitly enforce it here so the invariant holds even if that logic changes.
    if claims.role != "admin":
        result = await uow.session.execute(select(User).where(User.id == claims.sub))
        user = result.scalar_one()
        user.role = "admin"
        await uow.commit()
        claims = UserClaims(
            sub=claims.sub,
            email=claims.email,
            role="admin",
            is_active=claims.is_active,
            theme=claims.theme,
        )

    token = encode_token(claims)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE,
        max_age=60 * int(config.JWT_EXPIRE_MINUTES),
    )
    return claims
