import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── Password routes removed — must return 404 ────────────────────────────────


async def test_register_password_route_returns_404() -> None:
    """POST /auth/register/password must be removed and return 404 (AC3)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/password",
            json={"email": "musashi@example.com", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 404


async def test_login_password_route_returns_404() -> None:
    """POST /auth/login/password must be removed and return 404 (AC3)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/login/password",
            json={"email": "musashi@example.com", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 404


# ── Route protection ──────────────────────────────────────────────────────────


async def test_protected_route_no_token_returns_401() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/me")
    assert response.status_code == 401


async def test_protected_route_member_token_succeeds() -> None:
    claims = UserClaims(
        sub="uuid-1", email="m@dojo.test", role="member", is_active=True
    )
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: claims
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "m@dojo.test"


async def test_admin_route_rejects_member_token() -> None:
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="uuid-2", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin-only", cookies={"access_token": token})
    assert response.status_code == 403


async def test_admin_route_accepts_admin_token() -> None:
    claims = UserClaims(sub="uuid-3", email="a@dojo.test", role="admin", is_active=True)
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin-only")
    assert response.status_code == 200


# ── Logout (issue #325) ────────────────────────────────────────────────────
#
# The endpoint itself already exists and works; nothing in the UI calls it
# yet (that's the frontend part of issue #325, covered by
# test_e2e_logout.py). The one genuinely uncovered backend behaviour is the
# cookie-clearing semantics: does the response actually instruct the browser
# to drop the access_token cookie, not just return a 200 body?


async def test_logout_clears_access_token_cookie() -> None:
    """POST /auth/logout must instruct the browser to expire access_token.

    FastAPI's Response.delete_cookie sets Max-Age=0 (and an epoch Expires) on
    a same-named Set-Cookie header, which is what actually clears the cookie
    client-side — the 200 status/body alone would not.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/logout", cookies={"access_token": "some-token"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie")
    assert set_cookie is not None, "logout must send a Set-Cookie header to clear the cookie"
    assert "access_token=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


async def test_logout_succeeds_without_existing_session() -> None:
    """POST /auth/logout is not gated behind auth — calling it with no cookie
    at all must still succeed (idempotent sign-out), not 401.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/auth/logout")
    assert response.status_code == 200
