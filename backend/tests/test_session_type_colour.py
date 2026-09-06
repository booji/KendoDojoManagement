"""
Tests for issue #76 — admin-configurable colour per session type.

Acceptance criteria:
  1. Admin can set a colour on any session type from the admin settings page
  2. Colour is persisted and returned on GET /session-types
  3. Calendar chips use the admin-chosen colour; fall back to auto-palette if no colour set
  4. Cancelled sessions remain fully grey regardless of type colour

Tests (unit/integration — in-memory fakes, no DB):
  - PUT /session-types/{id} with valid hex colour succeeds (admin) and colour is returned
  - GET /session-types returns colour field (None when not set, hex string when set)
  - PUT /session-types/{id} returns 404 for unknown id
  - PUT /session-types/{id} returns 403 for non-admin
  - PUT /session-types/{id} with null colour clears the colour

NO real DB: the shared in-memory fakes stand in. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import UserClaims
from app.main import app
from app.sessions.dependencies import get_session_type_repo
from tests.fake_repositories import (
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> InMemorySessionTypeRepository:
    repo = InMemorySessionTypeRepository()
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_type(
    repo: InMemorySessionTypeRepository, *, name: str = "Keiko"
) -> dict[str, Any]:
    """Add a session type directly to the stub store.

    The stub's add() does not include a 'colour' key; any colour in the
    HTTP response must come from the router's response model applying its
    default.
    """
    return await repo.add(name)


# ---------------------------------------------------------------------------
# GET /session-types — colour field is present
# ---------------------------------------------------------------------------


async def test_list_session_types_includes_colour_field_when_none(type_repo) -> None:
    """GET /session-types must include colour: null for a type with no colour set."""
    await _seed_type(type_repo, name="Keiko")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/session-types")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "colour" in data[0]
    assert data[0]["colour"] is None


async def test_list_session_types_returns_colour_when_set(type_repo) -> None:
    """GET /session-types must return the stored hex colour string after it has been set.

    Uses the PUT endpoint (which does not exist yet) to set the colour, then
    asserts GET /session-types reflects it.  This test is red until both
    PUT /session-types/{id} and the colour field on SessionTypeRead exist.
    """
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Jodo")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        put_response = await c.put(
            f"/session-types/{st['id']}", json={"colour": "#ff5733"}
        )
        assert put_response.status_code == 200
        response = await c.get("/session-types")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["colour"] == "#ff5733"


# ---------------------------------------------------------------------------
# PUT /session-types/{id} — set colour (admin)
# ---------------------------------------------------------------------------


async def test_put_session_type_colour_succeeds_for_admin(type_repo) -> None:
    """PUT /session-types/{id} with a valid hex colour must return 200 and the updated record."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Iaido")
    payload = {"colour": "#3498db"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/session-types/{st['id']}", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == st["id"]
    assert body["colour"] == "#3498db"


async def test_put_session_type_colour_persisted_on_get(type_repo) -> None:
    """After PUT /session-types/{id}, GET /session-types must reflect the new colour."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Naginata")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.put(f"/session-types/{st['id']}", json={"colour": "#e74c3c"})
        list_response = await c.get("/session-types")
    assert list_response.status_code == 200
    data = list_response.json()
    matching = [item for item in data if item["id"] == st["id"]]
    assert len(matching) == 1
    assert matching[0]["colour"] == "#e74c3c"


async def test_put_session_type_colour_not_found(type_repo) -> None:
    """PUT /session-types/{id} with an unknown id must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/session-types/{fake_id}", json={"colour": "#000000"})
    assert response.status_code == 404


async def test_put_session_type_colour_forbidden_for_member(type_repo) -> None:
    """PUT /session-types/{id} must return 403 for a non-admin user."""
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    st = await _seed_type(type_repo, name="Kendo")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/session-types/{st['id']}",
            json={"colour": "#aabbcc"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


async def test_put_session_type_colour_null_clears_colour(type_repo) -> None:
    """PUT /session-types/{id} with colour: null must clear any existing colour."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Bojutsu")
    # First set a colour
    await type_repo.update(st["id"], "#123456")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/session-types/{st['id']}", json={"colour": None})
    assert response.status_code == 200
    body = response.json()
    assert body["colour"] is None
