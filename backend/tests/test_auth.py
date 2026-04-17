import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.base import Base
from app.db.unit_of_work import SQLAlchemyUnitOfWork
from app.dependencies import get_uow
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def _engine():
    eng = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_client(_engine):
    factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def _override():
        async with SQLAlchemyUnitOfWork(factory) as uow:
            yield uow

    app.dependency_overrides[get_uow] = _override
    yield _engine
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── Registration ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_first_user_becomes_admin(db_client) -> None:
    """First registration on a fresh instance gets admin role."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/register/password",
            json={"email": "musashi@example.com", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "musashi@example.com"
    assert body["role"] == "admin"
    assert "sub" in body
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.anyio
async def test_register_subsequent_user_is_member(db_client) -> None:
    """Second and later registrations get member role."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "first@example.com", "password": "Str0ng!Pass"},
        )
        response = await c.post(
            "/auth/register/password",
            json={"email": "musashi@example.com", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 201
    assert response.json()["role"] == "member"


@pytest.mark.anyio
async def test_register_duplicate_email_returns_409(db_client) -> None:
    payload = {"email": "dupe@dojo.test", "password": "Str0ng!Pass"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/auth/register/password", json=payload)
        response = await c.post("/auth/register/password", json=payload)
    assert response.status_code == 409


# ── Login ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_login_returns_jwt(db_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "login@dojo.test", "password": "Str0ng!Pass"},
        )
        response = await c.post(
            "/auth/login/password",
            json={"email": "login@dojo.test", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 200
    assert response.json() == {"detail": "logged in"}
    assert "access_token" in response.cookies


@pytest.mark.anyio
async def test_login_wrong_password_returns_401(db_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "badpass@dojo.test", "password": "Str0ng!Pass"},
        )
        response = await c.post(
            "/auth/login/password",
            json={"email": "badpass@dojo.test", "password": "wrongpassword"},
        )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_login_unknown_email_returns_401(db_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/login/password",
            json={"email": "nobody@dojo.test", "password": "whatever"},
        )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_login_deactivated_account_returns_403(db_client) -> None:
    engine = db_client
    from sqlalchemy import update

    from app.auth.db_models import User

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post(
            "/auth/register/password",
            json={"email": "inactive@dojo.test", "password": "Str0ng!Pass"},
        )
    user_id = resp.json()["sub"]

    async with engine.begin() as conn:
        await conn.execute(
            update(User).where(User.id == user_id).values(is_active=False)
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/auth/login/password",
            json={"email": "inactive@dojo.test", "password": "Str0ng!Pass"},
        )
    assert response.status_code == 403


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


# ── Password storage ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_password_not_stored_in_plaintext(db_client) -> None:
    engine = db_client
    from sqlalchemy import select

    from app.auth.db_models import User

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": "hash@dojo.test", "password": "MySecret123!"},
        )

    async with engine.connect() as conn:
        result = await conn.execute(select(User).where(User.email == "hash@dojo.test"))
        user = result.fetchone()

    assert user is not None
    assert user.hashed_password != "MySecret123!"
    assert user.hashed_password.startswith("$2")  # bcrypt prefix
