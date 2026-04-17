from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Cookie, HTTPException, status

from app.auth.models import UserClaims
from app.auth.token import decode_token


@lru_cache(maxsize=8)
def require_role(
    role: Literal["admin", "member"] | None = None,
) -> type:
    """
    Returns a stable callable (cached per role) usable as a FastAPI dependency.
    Use module-level constants REQUIRE_MEMBER / REQUIRE_ADMIN for test overrides.
    """

    async def _guard(
        access_token: Annotated[str | None, Cookie()] = None,
    ) -> UserClaims:
        if access_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            claims = decode_token(access_token)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not claims.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if claims.recovery_session:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if role == "admin" and claims.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return claims

    # Give each guard a unique __name__ so FastAPI treats them as distinct deps
    _guard.__name__ = f"_guard_{role or 'any'}"
    return _guard


# Stable module-level references — use these in dependency_overrides
REQUIRE_MEMBER = require_role()
REQUIRE_ADMIN = require_role("admin")
