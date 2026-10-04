from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from app.auth.accounts import sign_in_email
from app.auth.db_models import Account
from app.auth.models import AccountClaims
from app.auth.token import decode_token, encode_token, renewal_due
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


async def _renew(
    request: Request,
    uow: AbstractUnitOfWork,
    claims: AccountClaims,
    session_started_at: int,
) -> AccountClaims:
    """Mint the slid token and hand back the claims it now carries.

    Role and ``is_active`` live in the token, so between logins the app is
    reading a snapshot of the user row. Renewal is the one moment that snapshot
    can be refreshed for free — the row is re-read here, so a demotion bites on
    this request rather than waiting out the token.

    A user who has been deleted or deactivated has no session left to slide:
    that is a 401, not a 403, so the SPA reads it as a sign-out and routes to
    the login page rather than papering the app in "Not authorized" toasts.

    The cookie is left to ``SessionRenewalMiddleware`` — see the reason there.
    """
    user = await uow.session.get(Account, claims.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    # The Member's address as of now: an admin may have changed it (#432).
    email = await sign_in_email(uow.session, user.id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    fresh = AccountClaims(
        sub=claims.sub,
        email=email,
        role=user.role,
        is_active=user.is_active,
    )
    request.state.renewed_token = encode_token(fresh, session_started_at)
    return fresh


@lru_cache(maxsize=8)
def require_role(
    role: Literal["admin", "member"] | None = None,
) -> type:
    """
    Returns a stable callable (cached per role) usable as a FastAPI dependency.
    Use module-level constants REQUIRE_MEMBER / REQUIRE_ADMIN for test overrides.
    """

    async def _guard(
        request: Request,
        uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
        access_token: Annotated[str | None, Cookie()] = None,
    ) -> AccountClaims:
        if access_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            claims = decode_token(access_token)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if claims.recovery_session:
            # Deliberately short-lived and scoped to the recovery endpoints —
            # never slid forward.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        session_started_at = renewal_due(access_token)
        if session_started_at is not None:
            claims = await _renew(request, uow, claims, session_started_at)

        # 401, not 403, and for the same reason as in ``_renew``: a deactivated
        # user has no session, so the SPA must route to /login rather than leave
        # the app rendered behind a "Not authorized" toast. Renewal only runs
        # past the halfway mark of a token's life, so splitting these two would
        # make the status code depend on how old the token happens to be.
        if not claims.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        # The role check stays a 403: the session is valid, this route is not.
        if role == "admin" and claims.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return claims

    # Give each guard a unique __name__ so FastAPI treats them as distinct deps
    _guard.__name__ = f"_guard_{role or 'any'}"
    return _guard


# Stable module-level references — use these in dependency_overrides
REQUIRE_MEMBER = require_role()
REQUIRE_ADMIN = require_role("admin")


async def require_passkey_enrolment(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Account:
    """The Account the caller may add a passkey to (#443).

    Either the one their session cookie names, or the one a recovery token
    names: redeeming a recovery code hands the SPA that token, which it sends
    as a Bearer header (it is never a cookie), and enrolling a new passkey is
    the only thing it is good for. Each is accepted only where it arrives —
    a recovery token in the cookie, or a session token in the header, is
    refused — so neither can stand in for the other here or anywhere else.

    The Account is re-read rather than trusted from the token: one deleted
    or deactivated since the token was minted gets nothing.
    """
    if authorization is not None and authorization.startswith("Bearer "):
        token, expect_recovery = authorization.removeprefix("Bearer "), True
    elif access_token is not None:
        token, expect_recovery = access_token, False
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        claims = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if claims.recovery_session != expect_recovery:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    account = await uow.session.get(Account, claims.sub)
    if account is None or not account.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return account
