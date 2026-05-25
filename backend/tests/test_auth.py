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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_protected_route_no_token_returns_401() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_admin_route_accepts_admin_token() -> None:
    claims = UserClaims(sub="uuid-3", email="a@dojo.test", role="admin", is_active=True)
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: claims
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/admin-only")
    assert response.status_code == 200
