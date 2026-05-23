"""
Tests for PATCH /auth/me/theme endpoint (issue #14).

The endpoint does not exist yet — all tests are expected to fail red
(404 Not Found or ImportError) until implementation is complete.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def _theme_engine():
    eng = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_client(_theme_engine):
    factory = async_sessionmaker(_theme_engine, expire_on_commit=False)

    async def _override():
        async with SQLAlchemyUnitOfWork(factory) as uow:
            yield uow

    app.dependency_overrides[get_uow] = _override
    yield _theme_engine
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── PATCH /auth/me/theme — happy paths ───────────────────────────────────────


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/register/password and /auth/login/password removed in issue #155",
)
@pytest.mark.anyio
async def test_patch_theme_light_returns_200(db_client) -> None:
    """Setting theme to 'light' returns 200 with updated UserClaims."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Register and log in to get a real user in the DB
        await c.post(
            "/auth/register/password",
            json={"email": "theme-light@dojo.test", "password": "Str0ng!Pass"},
        )
        login = await c.post(
            "/auth/login/password",
            json={"email": "theme-light@dojo.test", "password": "Str0ng!Pass"},
        )
        token = login.cookies["access_token"]

        response = await c.patch(
            "/auth/me/theme",
            json={"theme": "light"},
            cookies={"access_token": token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "light"
    assert body["email"] == "theme-light@dojo.test"


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/register/password and /auth/login/password removed in issue #155",
)
@pytest.mark.anyio
async def test_patch_theme_dark_returns_200(db_client) -> None:
    """Setting theme to 'dark' returns 200 with updated UserClaims."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "theme-dark@dojo.test", "password": "Str0ng!Pass"},
        )
        login = await c.post(
            "/auth/login/password",
            json={"email": "theme-dark@dojo.test", "password": "Str0ng!Pass"},
        )
        token = login.cookies["access_token"]

        response = await c.patch(
            "/auth/me/theme",
            json={"theme": "dark"},
            cookies={"access_token": token},
        )

    assert response.status_code == 200
    assert response.json()["theme"] == "dark"


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/register/password and /auth/login/password removed in issue #155",
)
@pytest.mark.anyio
async def test_patch_theme_system_returns_200(db_client) -> None:
    """Setting theme to 'system' returns 200 with updated UserClaims."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "theme-system@dojo.test", "password": "Str0ng!Pass"},
        )
        login = await c.post(
            "/auth/login/password",
            json={"email": "theme-system@dojo.test", "password": "Str0ng!Pass"},
        )
        token = login.cookies["access_token"]

        response = await c.patch(
            "/auth/me/theme",
            json={"theme": "system"},
            cookies={"access_token": token},
        )

    assert response.status_code == 200
    assert response.json()["theme"] == "system"


# ── PATCH /auth/me/theme — validation error ───────────────────────────────────


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/register/password and /auth/login/password removed in issue #155",
)
@pytest.mark.anyio
async def test_patch_theme_invalid_value_returns_422(db_client) -> None:
    """An unrecognised theme value ('purple') must be rejected with 422."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "theme-bad@dojo.test", "password": "Str0ng!Pass"},
        )
        login = await c.post(
            "/auth/login/password",
            json={"email": "theme-bad@dojo.test", "password": "Str0ng!Pass"},
        )
        token = login.cookies["access_token"]

        response = await c.patch(
            "/auth/me/theme",
            json={"theme": "purple"},
            cookies={"access_token": token},
        )

    assert response.status_code == 422


# ── PATCH /auth/me/theme — unauthenticated ────────────────────────────────────


@pytest.mark.anyio
async def test_patch_theme_without_auth_returns_401() -> None:
    """Calling PATCH /auth/me/theme without a token must return 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch("/auth/me/theme", json={"theme": "dark"})

    assert response.status_code == 401


# ── GET /auth/me — theme field present in UserClaims ─────────────────────────


@pytest.mark.anyio
async def test_get_me_includes_theme_field() -> None:
    """GET /auth/me must return a 'theme' field in the UserClaims payload."""
    claims = UserClaims(
        sub="uuid-theme-1",
        email="me-theme@dojo.test",
        role="member",
        is_active=True,
        theme="system",
    )
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert "theme" in body
    assert body["theme"] == "system"


@pytest.mark.anyio
async def test_get_me_theme_defaults_to_system() -> None:
    """When no theme is stored, GET /auth/me must default to 'system'."""
    # UserClaims without explicit theme — default must be 'system'
    claims = UserClaims(
        sub="uuid-theme-2",
        email="me-default@dojo.test",
        role="member",
        is_active=True,
    )
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["theme"] == "system"
