from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException, status

from app.auth.auth_session_repository import AbstractAuthSessionRepository
from app.auth.auth_sessions import resolve_auth_session
from app.auth.db_models import Account
from app.auth.dependencies import get_auth_session_repo
from app.auth.models import AccountClaims
from app.auth.token import decode_token
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


@lru_cache(maxsize=8)
def require_role(
    role: Literal["admin", "member"] | None = None,
) -> type:
    """
    Returns a stable callable (cached per role) usable as a FastAPI dependency.
    Use module-level constants REQUIRE_MEMBER / REQUIRE_ADMIN for test overrides.
    """

    async def _guard(
        repo: Annotated[AbstractAuthSessionRepository, Depends(get_auth_session_repo)],
        access_token: Annotated[str | None, Cookie()] = None,
    ) -> AccountClaims:
        if access_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        claims = await resolve_auth_session(repo, access_token)
        # 401, not 403, for a deactivated Account as for a missing Auth Session:
        # it has none either way, so the SPA must route to /login rather
        # than leave the app rendered behind a "Not authorized" toast (#396).
        if claims is None or not claims.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        # The role check stays a 403: the Auth Session is valid, this route is not.
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
    repo: Annotated[AbstractAuthSessionRepository, Depends(get_auth_session_repo)],
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Account:
    """The Account the caller may add a passkey to (#443).

    Either the one their Auth Session names, or the one a recovery token
    names: redeeming a recovery code hands the SPA that token, which it sends
    as a Bearer header (it is never a cookie), and enrolling a new passkey is
    the only thing it is good for. Each is accepted only where it arrives —
    a recovery token in the cookie names no Auth Session, and only a recovery
    token is accepted in the header — so neither can stand in for the other.

    The Account is re-read rather than trusted from the token: one deleted
    or deactivated since the token was minted gets nothing.
    """
    if authorization is not None and authorization.startswith("Bearer "):
        try:
            claims = decode_token(authorization.removeprefix("Bearer "))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not claims.recovery_session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        account_id = claims.sub
    elif access_token is not None:
        session_claims = await resolve_auth_session(repo, access_token)
        if session_claims is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        account_id = session_claims.sub
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    account = await uow.session.get(Account, account_id)
    if account is None or not account.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return account
