"""First-run setup router (issue #38).

Exposes /setup, /setup/passkey/begin, and /setup/passkey/complete.

All three endpoints share the same guard: _is_claimed().  The instance is
claimed once any Admin Account exists (#589).

Counting Admin Accounts, not passkeys or users, means:
- Phantom Accounts from an abandoned begin ceremony are members (admin is
  granted only when a claim completes), so they do NOT block a legitimate
  first-run setup.
- The claim stays closed when the only Admin deletes their only passkey to
  re-enrol: a leaked SETUP_TOKEN never reopens a claimed instance.
- Nothing removes the last Admin Account: archiving or suspending the last
  Admin who may sign in is refused, and erasure needs a different, signed-in
  Admin to act.
- The guard is identical for GET, begin, and complete — no fragile asymmetry.

begin and complete carry a second gate in front of that one: the
pre-provisioned SETUP_TOKEN (ADR-0003, #402). GET stays open so the SPA can
decide whether to render the setup page.
"""

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app import config
from app.auth.accounts import account_for_member, delete_account
from app.auth.auth_session_repository import AbstractAuthSessionRepository
from app.auth.auth_sessions import start_auth_session
from app.auth.db_models import Account, PasskeyCredential
from app.auth.dependencies import get_auth_session_repo
from app.auth.passkey_service import register_passkey_begin, register_passkey_complete
from app.auth.schemas import (
    AccountClaims,
    PasskeyRegisterCompleteRequest,
    SetupBeginRequest,
)
from app.auth.session_cookie import set_session_cookie
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.admin_directory import SqlAdminDirectory
from app.members.db_models import Member

router = APIRouter(prefix="/setup", tags=["setup"])
_log = logging.getLogger(__name__)

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

    Called from inside the handlers, after _is_claimed(), so a claimed
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


async def _is_claimed(uow: AbstractUnitOfWork) -> bool:
    """True once any Admin Account exists, whatever its passkeys or status."""
    return await SqlAdminDirectory(uow.session).any_admin_account()


async def _discard_abandoned_claims(uow: AbstractUnitOfWork, claimant: Account) -> None:
    """Remove every other claim attempt's Member and Account (#446).

    A claim begun under one address and finished under another leaves the
    first attempt's Member on the roster and its Account, with no passkey,
    that nobody can use. Only Members a claim created carry
    `claim_attempted_at`, so the roster is never touched.
    """
    session = uow.session
    abandoned = (
        (
            await session.execute(
                select(Member.id).where(
                    Member.claim_attempted_at.is_not(None),
                    Member.id != claimant.member_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for member_id in abandoned:
        account = await account_for_member(session, member_id)
        if account is not None:
            await delete_account(session, account.id)
    await session.execute(delete(Member).where(Member.id.in_(abandoned)))
    await session.execute(
        update(Member)
        .where(Member.id == claimant.member_id)
        .values(claim_attempted_at=None)
    )
    await uow.commit()


@router.get("")
async def get_setup(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    """Return 200 when instance is unconfigured, 404 otherwise."""
    if await _is_claimed(uow):
        raise _ALREADY_DONE
    return {"detail": "Setup available"}


@router.post("/passkey/begin")
async def setup_passkey_begin(
    payload: SetupBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    x_setup_token: SetupTokenHeader = None,
) -> dict:
    """Begin passkey registration for the first admin, creating their Member
    and Account in this one transaction (#432)."""
    if await _is_claimed(uow):
        raise _ALREADY_DONE
    _require_setup_token(x_setup_token)
    return await register_passkey_begin(
        payload.email, payload.first_name, payload.surname, uow
    )


@router.post("/passkey/complete", status_code=201)
async def setup_passkey_complete(
    payload: PasskeyRegisterCompleteRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    auth_sessions: Annotated[
        AbstractAuthSessionRepository, Depends(get_auth_session_repo)
    ],
    x_setup_token: SetupTokenHeader = None,
) -> AccountClaims:
    """Complete passkey registration, promote user to admin, set cookie."""
    if await _is_claimed(uow):
        raise _ALREADY_DONE
    _require_setup_token(x_setup_token)

    claims = await register_passkey_complete(payload, uow)

    # The one place admin is granted: the claim has completed. Begin creates
    # the Account as a member, so an abandoned claim leaves no admin account
    # behind for a later claim to finish (#432).
    user = await uow.session.get(Account, claims.sub)
    assert user is not None  # register_passkey_complete just enrolled it
    if claims.role != "admin":
        user.role = "admin"
        await uow.commit()
        claims = AccountClaims(
            sub=claims.sub,
            email=claims.email,
            role="admin",
        )

    # Signed in before the tidy-up below, which may roll back: the claim has
    # succeeded, so its Auth Session must not depend on the clean-up. The
    # passkey is the one just enrolled; a fresh claim's Account has no other.
    passkey_id = (
        await uow.session.execute(
            select(PasskeyCredential.id)
            .where(PasskeyCredential.user_id == claims.sub)
            .order_by(PasskeyCredential.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    token = await start_auth_session(auth_sessions, claims.sub, passkey_id)
    await uow.commit()

    # After the admin grant has committed, and best-effort: the claim has
    # succeeded, and a failure tidying up must not turn it into an error the
    # claimant cannot retry (setup now answers 404).
    try:
        await _discard_abandoned_claims(uow, user)
    except SQLAlchemyError:
        await uow.rollback()
        _log.exception("Could not remove abandoned setup claim attempts")

    log_security_event("setup_claim", "success", user_id=claims.sub)
    set_session_cookie(response, token)
    return claims
