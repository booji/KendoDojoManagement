"""Unit tests for app/auth/guards.require_role — the dependency that gates
every authenticated endpoint in the app.

These exist because the guard had no tests of its own: authorization coverage
lived in route tests that overrode ``REQUIRE_ADMIN`` with a member stub and
then asserted 403. Such a test replaces the code under test, so it passes even
when the route's guard is deleted. The guard is exercised directly here, and
route tests hand it a real token instead (see the ``cookies_for`` fixture).

No DB, no app — the guard is called as a plain callable.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER, require_role
from app.auth.models import UserClaims
from app.auth.token import encode_recovery_token, encode_token

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)
_INACTIVE = UserClaims(
    sub="inactive-uuid", email="inactive@dojo.test", role="admin", is_active=False
)


async def _call(guard, claims: UserClaims | None) -> UserClaims:
    token = encode_token(claims) if claims is not None else None
    return await _invoke(guard, token)


async def _invoke(guard, token: str | None) -> UserClaims:
    """Call the guard the way FastAPI would.

    The request and unit of work are the sliding-renewal seam (#387); a fresh
    token is never due for renewal, so neither is touched by these tests. See
    test_session_renewal.py for the renewal path itself.
    """
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    return await guard(request=request, uow=None, access_token=token)


# ---------------------------------------------------------------------------
# REQUIRE_ADMIN
# ---------------------------------------------------------------------------


async def test_require_admin_rejects_member_with_403() -> None:
    """A valid member token must not satisfy the admin guard."""
    with pytest.raises(HTTPException) as exc:
        await _call(REQUIRE_ADMIN, _MEMBER)

    assert exc.value.status_code == 403


async def test_require_admin_accepts_admin() -> None:
    claims = await _call(REQUIRE_ADMIN, _ADMIN)

    assert claims.sub == _ADMIN.sub
    assert claims.role == "admin"


# ---------------------------------------------------------------------------
# REQUIRE_MEMBER — any authenticated active user, admin included
# ---------------------------------------------------------------------------


async def test_require_member_accepts_member() -> None:
    claims = await _call(REQUIRE_MEMBER, _MEMBER)

    assert claims.role == "member"


async def test_require_member_accepts_admin() -> None:
    """REQUIRE_MEMBER means 'authenticated', not 'not an admin'."""
    claims = await _call(REQUIRE_MEMBER, _ADMIN)

    assert claims.role == "admin"


# ---------------------------------------------------------------------------
# Shared rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_missing_cookie_returns_401(guard) -> None:
    with pytest.raises(HTTPException) as exc:
        await _call(guard, None)

    assert exc.value.status_code == 401


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_undecodable_token_returns_401(guard) -> None:
    with pytest.raises(HTTPException) as exc:
        await _invoke(guard, "not-a-jwt")

    assert exc.value.status_code == 401


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_inactive_user_returns_403(guard) -> None:
    """Deactivating a member must lock them out before their token expires."""
    with pytest.raises(HTTPException) as exc:
        await _call(guard, _INACTIVE)

    assert exc.value.status_code == 403


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_recovery_session_token_returns_403(guard) -> None:
    """A recovery session may only reach the recovery endpoints, not the app."""
    token = encode_recovery_token("member-uuid", "member@dojo.test")

    with pytest.raises(HTTPException) as exc:
        await _invoke(guard, token)

    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Caching contract — dependency_overrides keys on identity
# ---------------------------------------------------------------------------


def test_require_role_returns_a_stable_callable_per_role() -> None:
    """Overrides are registered by identity, so the guard must be cached."""
    assert require_role("admin") is REQUIRE_ADMIN
    assert require_role() is REQUIRE_MEMBER
    assert REQUIRE_ADMIN is not REQUIRE_MEMBER
