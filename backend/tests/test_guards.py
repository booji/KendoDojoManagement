"""Unit tests for app/auth/guards.require_role — the dependency that gates
every authenticated endpoint in the app.

These exist because the guard had no tests of its own: authorization coverage
lived in route tests that overrode ``REQUIRE_ADMIN`` with a member stub and
then asserted 403. Such a test replaces the code under test, so it passes even
when the route's guard is deleted. The guard is exercised directly here, and
route tests hand it a real Auth Session instead (see the ``cookies_for``
fixture).

No DB, no app — the guard is called as a plain callable over an in-memory
Auth Session repository.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER, require_role
from app.auth.models import AccountClaims
from tests.fake_repositories import InMemoryAuthSessionRepository

_ADMIN = AccountClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = AccountClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)
_INACTIVE = AccountClaims(
    sub="inactive-uuid", email="inactive@dojo.test", role="admin", is_active=False
)


async def _call(guard, claims: AccountClaims | None) -> AccountClaims:
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(claims) if claims is not None else None
    return await _invoke(guard, token, repo)


async def _invoke(
    guard, token: str | None, repo: InMemoryAuthSessionRepository | None = None
) -> AccountClaims:
    """Call the guard the way FastAPI would."""
    return await guard(repo=repo or InMemoryAuthSessionRepository(), access_token=token)


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


async def test_role_is_read_from_the_account_on_every_request() -> None:
    """A demotion bites on the next request, with no re-login and no
    revocation hook: the role lives on the Account, not the Auth Session."""
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_ADMIN)
    repo.seed_account(_ADMIN.model_copy(update={"role": "member"}))

    with pytest.raises(HTTPException) as exc:
        await _invoke(REQUIRE_ADMIN, token, repo)

    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Shared rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_missing_cookie_returns_401(guard) -> None:
    with pytest.raises(HTTPException) as exc:
        await _call(guard, None)

    assert exc.value.status_code == 401


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_unknown_cookie_returns_401(guard) -> None:
    """A cookie value with no Auth Session behind it is no session at all."""
    with pytest.raises(HTTPException) as exc:
        await _invoke(guard, "no-such-auth-session")

    assert exc.value.status_code == 401


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_inactive_user_returns_401(guard) -> None:
    """Deactivating a member must lock them out before their token expires.

    401 rather than 403 (#396): a deactivated user
    has no session either way, so the SPA reads it as a sign-out and routes to
    the login page instead of leaving the app rendered behind a toast.
    """
    with pytest.raises(HTTPException) as exc:
        await _call(guard, _INACTIVE)

    assert exc.value.status_code == 401


@pytest.mark.parametrize("guard", [REQUIRE_MEMBER, REQUIRE_ADMIN])
async def test_recovery_auth_session_returns_403(guard) -> None:
    """A recovery Auth Session may only enrol a passkey, never reach the app.

    403, not 401: it is a real, live Auth Session, just not for this route.
    """
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_MEMBER, kind="recovery")

    with pytest.raises(HTTPException) as exc:
        await _invoke(guard, token, repo)

    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Caching contract — dependency_overrides keys on identity
# ---------------------------------------------------------------------------


def test_require_role_returns_a_stable_callable_per_role() -> None:
    """Overrides are registered by identity, so the guard must be cached."""
    assert require_role("admin") is REQUIRE_ADMIN
    assert require_role() is REQUIRE_MEMBER
    assert REQUIRE_ADMIN is not REQUIRE_MEMBER
