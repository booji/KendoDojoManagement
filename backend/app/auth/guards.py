from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException, status

from app.auth.auth_session_repository import AbstractAuthSessionRepository
from app.auth.auth_sessions import resolve_auth_session
from app.auth.db_models import Account
from app.auth.dependencies import get_auth_session_repo
from app.auth.models import AccountClaims
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
        if claims is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if claims.recovery_session:
            # Good only for enrolling a passkey (#486), never the app.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        # 401, not 403, for a deactivated Account as for a missing Auth Session:
        # it has none either way, so the SPA must route to /login rather
        # than leave the app rendered behind a "Not authorized" toast (#396).
        if not claims.is_active:
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

    Either the one their Auth Session names, or the one a recovery Auth
    Session names: redeeming a recovery code hands the SPA that token, which
    it sends as a Bearer header (it is never a cookie), and enrolling a new
    passkey is the only thing it is good for. Each kind is accepted only where
    it arrives — a session in the cookie, a recovery token in the header — so
    neither can stand in for the other.

    The Account is re-read rather than trusted from the Auth Session: one
    deleted or deactivated since gets nothing.
    """
    if authorization is not None and authorization.startswith("Bearer "):
        token, expect_recovery = authorization.removeprefix("Bearer "), True
    elif access_token is not None:
        token, expect_recovery = access_token, False
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    claims = await resolve_auth_session(repo, token)
    if claims is None or claims.recovery_session != expect_recovery:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    account = await uow.session.get(Account, claims.sub)
    if account is None or not account.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return account
