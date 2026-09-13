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

begin and complete carry a second gate in front of that one: the
pre-provisioned SETUP_TOKEN (ADR-0003, #402). GET stays open so the SPA can
decide whether to render the setup page.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import func, select

from app import config
from app.auth.db_models import PasskeyCredential, User
from app.auth.models import (
    PasskeyBeginRequest,
    PasskeyRegisterCompleteRequest,
    UserClaims,
)
from app.auth.passkey_service import register_passkey_begin, register_passkey_complete
from app.auth.session_cookie import set_session_cookie
from app.auth.token import encode_token
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow

router = APIRouter(prefix="/setup", tags=["setup"])

_ALREADY_DONE = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Setup already completed",
)

# Deliberately distinct from _ALREADY_DONE's 404: GET /setup already reveals
# unclaimed state, so there is nothing to hide here, and an operator needs to
# tell "wrong token" from "already claimed" (ADR-0003).
_BAD_SETUP_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid setup token",
)

SetupTokenHeader = Annotated[str | None, Header(alias="X-Setup-Token")]


def _require_setup_token(presented: str | None) -> None:
    """Reject unless the caller presents the pre-provisioned SETUP_TOKEN.

    Called from inside the handlers, after _has_registered_user(), so a claimed
    instance still answers 404 whatever token is presented — a dependency would
    run first and turn that into a 401.

    A blank configured token never matches: validate_startup_config() refuses
    to boot without one, but a test or a hand-rolled run that skips lifespan()
    must not end up with "" == "" opening the claim to an empty header.
    """
    configured = config.SETUP_TOKEN
    # Compared as bytes: a header carrying a non-ASCII character (Starlette
    # decodes headers as latin-1) makes compare_digest raise TypeError on str
    # arguments, turning a wrong token into a 500.
    if (
        not configured.strip()
        or presented is None
        or not secrets.compare_digest(
            presented.encode("utf-8", "surrogateescape"),
            configured.encode("utf-8", "surrogateescape"),
        )
    ):
        log_security_event("setup_claim", "failure", user_id=None)
        raise _BAD_SETUP_TOKEN


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
    x_setup_token: SetupTokenHeader = None,
) -> dict:
    """Begin passkey registration for the first admin user."""
    if await _has_registered_user(uow):
        raise _ALREADY_DONE
    _require_setup_token(x_setup_token)
    return await register_passkey_begin(payload.email, uow, allow_bootstrap=True)


@router.post("/passkey/complete", status_code=201)
async def setup_passkey_complete(
    payload: PasskeyRegisterCompleteRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    x_setup_token: SetupTokenHeader = None,
) -> UserClaims:
    """Complete passkey registration, promote user to admin, set cookie."""
    if await _has_registered_user(uow):
        raise _ALREADY_DONE
    _require_setup_token(x_setup_token)

    claims = await register_passkey_complete(payload, uow, allow_bootstrap=True)

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
        )

    log_security_event("setup_claim", "success", user_id=claims.sub)
    token = encode_token(claims)
    set_session_cookie(response, token)
    return claims
