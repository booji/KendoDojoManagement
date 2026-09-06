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
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/register/password",
            json={"email": "musashi@example.com", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 404


async def test_login_password_route_returns_404() -> None:
    """POST /auth/login/password must be removed and return 404 (AC3)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/auth/login/password",
            json={"email": "musashi@example.com", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 404


# ── Route protection ──────────────────────────────────────────────────────────


async def test_protected_route_no_token_returns_401() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/me")
    assert response.status_code == 401


async def test_protected_route_member_token_succeeds() -> None:
    claims = UserClaims(
        sub="uuid-1", email="m@dojo.test", role="member", is_active=True
    )
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: claims
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/auth/admin-only", cookies={"access_token": token})
    assert response.status_code == 403


async def test_admin_route_accepts_admin_token() -> None:
    claims = UserClaims(sub="uuid-3", email="a@dojo.test", role="admin", is_active=True)
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/auth/logout", cookies={"access_token": "some-token"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie")
    assert (
        set_cookie is not None
    ), "logout must send a Set-Cookie header to clear the cookie"
    assert "access_token=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


async def test_logout_succeeds_without_existing_session() -> None:
    """POST /auth/logout is not gated behind auth — calling it with no cookie
    at all must still succeed (idempotent sign-out), not 401.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/auth/logout")
    assert response.status_code == 200


async def test_logout_cookie_attributes_match_the_login_cookie() -> None:
    """The clearing Set-Cookie must mirror the attributes the cookie was set with.

    A cookie is identified for overwrite by (name, domain, path), and browsers
    apply their own rules to SameSite/Secure — so a clear that omits the
    attributes login used relies on Starlette's defaults happening to coincide
    with them. They do today by accident, not by contract: a future change to
    the login cookie's path or domain would silently stop logout clearing
    anything. Assert parity instead of the coincidence.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        cleared = (await c.post("/auth/logout")).headers.get("set-cookie", "")

    assert "Path=/" in cleared
    assert "SameSite=strict" in cleared
    assert "HttpOnly" in cleared


async def test_logout_clears_the_readable_theme_cookie() -> None:
    """Logout must drop the JS-readable theme cookie along with the session (#324)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/auth/logout", cookies={"theme": "dark"})

    headers = response.headers.get_list("set-cookie")
    theme_header = next((h for h in headers if h.startswith("theme=")), None)
    assert theme_header is not None, "logout must send a Set-Cookie clearing theme"
    assert "Max-Age=0" in theme_header or "max-age=0" in theme_header.lower()
