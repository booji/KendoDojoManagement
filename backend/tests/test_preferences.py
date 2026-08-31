"""
Unit tests for issue #26 — User preferences API (theme persistence).

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. GET /users/me/preferences returns {"theme": "system"} for no saved preference
  2. PUT /users/me/preferences with {"theme": "dark"} persists and returns it
  3. PUT /users/me/preferences with an invalid theme value returns 422
  4. GET /users/me/preferences returns 401 for unauthenticated requests
  5. PUT /users/me/preferences returns 401 for unauthenticated requests
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.users.dependencies import get_user_prefs_repo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_SUB = "user-uuid-prefs"

_MEMBER_CLAIMS = UserClaims(
    sub=_USER_SUB, email="prefs@dojo.test", role="member", is_active=True
)


def _member_override():
    return _MEMBER_CLAIMS


# ---------------------------------------------------------------------------
# Stub repository — in-memory stand-in for user preferences persistence
# ---------------------------------------------------------------------------


class StubUserPrefsRepo:
    """Stores theme preference per user_id in memory."""

    def __init__(self) -> None:
        self._store: dict[str, str | None] = {}

    async def get_theme(self, user_id: str) -> str | None:
        """Return the stored theme for a user, or None if not set."""
        return self._store.get(user_id)

    async def set_theme(self, user_id: str, theme: str) -> str:
        """Persist the theme for a user and return the new value."""
        self._store[user_id] = theme
        return theme


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def prefs_repo() -> StubUserPrefsRepo:
    repo = StubUserPrefsRepo()
    app.dependency_overrides[get_user_prefs_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — GET /users/me/preferences returns {"theme": "system"} when no pref stored
# ---------------------------------------------------------------------------


async def test_get_preferences_returns_system_when_no_preference(prefs_repo) -> None:
    """A user with no saved theme preference gets {"theme": "system"}."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/preferences")

    assert response.status_code == 200
    assert response.json() == {"theme": "system"}


async def test_get_preferences_response_has_theme_key(prefs_repo) -> None:
    """Response body always contains the 'theme' key."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/preferences")

    assert "theme" in response.json()


# ---------------------------------------------------------------------------
# AC2 — PUT /users/me/preferences persists the theme and returns it
# ---------------------------------------------------------------------------


async def test_put_preferences_dark_persists_and_returns_dark(prefs_repo) -> None:
    """PUT {"theme": "dark"} returns 200 with {"theme": "dark"}."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": "dark"})

    assert response.status_code == 200
    assert response.json() == {"theme": "dark"}


async def test_put_preferences_light_persists_and_returns_light(prefs_repo) -> None:
    """PUT {"theme": "light"} returns 200 with {"theme": "light"}."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": "light"})

    assert response.status_code == 200
    assert response.json() == {"theme": "light"}


async def test_put_preferences_persisted_value_visible_in_subsequent_get(
    prefs_repo,
) -> None:
    """Theme set via PUT is returned by subsequent GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put("/users/me/preferences", json={"theme": "dark"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/preferences")

    assert response.status_code == 200
    assert response.json() == {"theme": "dark"}


async def test_put_preferences_overwrites_previous_value(prefs_repo) -> None:
    """A second PUT overwrites the first preference."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put("/users/me/preferences", json={"theme": "light"})
        await c.put("/users/me/preferences", json={"theme": "dark"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/preferences")

    assert response.json() == {"theme": "dark"}


async def test_put_preferences_system_round_trips(prefs_repo) -> None:
    """PUT {"theme": "system"} returns {"theme": "system"}."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": "system"})

    assert response.status_code == 200
    assert response.json() == {"theme": "system"}


# ---------------------------------------------------------------------------
# AC3 — PUT with invalid theme returns 422
# ---------------------------------------------------------------------------


async def test_put_preferences_invalid_theme_returns_422(prefs_repo) -> None:
    """An unrecognised theme value must be rejected with 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": "purple"})

    assert response.status_code == 422


async def test_put_preferences_empty_theme_returns_422(prefs_repo) -> None:
    """An empty string theme must be rejected with 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": ""})

    assert response.status_code == 422


async def test_put_preferences_missing_theme_key_returns_422(prefs_repo) -> None:
    """A payload missing the 'theme' key must be rejected with 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC4 — GET /users/me/preferences returns 401 for unauthenticated requests
# ---------------------------------------------------------------------------


async def test_get_preferences_unauthenticated_returns_401(prefs_repo) -> None:
    """No credentials → 401 on GET."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/preferences")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC5 — PUT /users/me/preferences returns 401 for unauthenticated requests
# ---------------------------------------------------------------------------


async def test_put_preferences_unauthenticated_returns_401(prefs_repo) -> None:
    """No credentials → 401 on PUT."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": "dark"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Issue #324 — the preferences endpoints seed a JS-readable `theme` cookie so
# a fresh client resolves the saved theme before first paint.
# ---------------------------------------------------------------------------


async def test_get_preferences_sets_readable_theme_cookie(prefs_repo) -> None:
    """GET must mirror the stored theme into a non-HttpOnly cookie."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await prefs_repo.set_theme(_USER_SUB, "dark")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/users/me/preferences")

    set_cookie = response.headers.get("set-cookie", "")
    assert "theme=dark" in set_cookie
    assert "HttpOnly" not in set_cookie, "the pre-paint script must be able to read it"


async def test_put_preferences_updates_the_readable_theme_cookie(prefs_repo) -> None:
    """Changing the theme rewrites the cookie, so a later reload resolves pre-paint."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/users/me/preferences", json={"theme": "light"})

    assert "theme=light" in response.headers.get("set-cookie", "")
