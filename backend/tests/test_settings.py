"""
Unit/integration tests for issue #12 — Dojo Settings (GET/PUT /settings/dojo, POST /settings/logo).

Uses StubRepository pattern — NO real DB.

Acceptance criteria covered here:
  1. GET /settings/dojo returns defaults when no settings saved
     (dojo_name="My Dojo", logo_url=None, primary_colour=default hex)
  2. PUT /settings/dojo persists dojo_name and primary_colour
  3. PUT /settings/dojo rejects primary_colour that fails WCAG 2.1 AA contrast
     (4.5:1 against white AND dark background)
  4. PUT /settings/dojo is admin-only (member token → 403)
  5. POST /settings/logo is admin-only (member token → 403)
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app

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


def _member_token() -> str:
    return encode_token(_MEMBER)


# ---------------------------------------------------------------------------
# Stub repository
# ---------------------------------------------------------------------------


class StubDojoSettingsRepo:
    """In-memory stand-in for a dojo settings repository."""

    _DEFAULT_COLOUR = "#4F46E5"  # indigo-600 — expected default

    def __init__(self) -> None:
        self._settings: dict[str, Any] | None = None

    async def get(self) -> dict[str, Any]:
        if self._settings is None:
            return {
                "dojo_name": "My Dojo",
                "logo_url": None,
                "primary_colour": self._DEFAULT_COLOUR,
                "checkin_window_before_minutes": 60,
                "checkin_window_after_minutes": 120,
                "background_image_url": None,
                "login_show_background": False,
                "login_show_logo": False,
                "login_show_name": False,
            }
        return dict(self._settings)

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        current = await self.get()
        current.update(data)
        self._settings = current
        return dict(self._settings)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepo:
    from app.settings.dependencies import get_dojo_settings_repo  # noqa: PLC0415

    repo = StubDojoSettingsRepo()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — GET /settings/dojo returns defaults when no settings saved
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_dojo_settings_returns_defaults_when_none_saved(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """GET /settings/dojo returns the hardcoded defaults when the DB has no row."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 200
    body = response.json()
    assert body["dojo_name"] == "My Dojo"
    assert body["logo_url"] is None
    assert "primary_colour" in body
    # Primary colour must be a valid hex string
    assert body["primary_colour"].startswith("#")
    assert len(body["primary_colour"]) in (4, 7)  # #RGB or #RRGGBB


@pytest.mark.anyio
async def test_get_dojo_settings_unauthenticated_returns_401(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """GET /settings/dojo without a token returns 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC2 — PUT /settings/dojo persists dojo_name and primary_colour
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_dojo_settings_persists_dojo_name(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """PUT /settings/dojo with a new dojo_name returns the updated value."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"dojo_name": "Tokyo Kendo Club"},
        )

    assert response.status_code == 200
    assert response.json()["dojo_name"] == "Tokyo Kendo Club"


@pytest.mark.anyio
async def test_put_dojo_settings_dojo_name_visible_on_get(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """Updated dojo_name is visible on a subsequent GET /settings/dojo."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put("/settings/dojo", json={"dojo_name": "Osaka Dojo"})
        get_resp = await c.get("/settings/dojo")

    assert get_resp.status_code == 200
    assert get_resp.json()["dojo_name"] == "Osaka Dojo"


@pytest.mark.anyio
async def test_put_dojo_settings_persists_primary_colour(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """PUT /settings/dojo with a WCAG-passing primary_colour persists the value."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # #1D4ED8 (blue-700) has >4.5:1 against white and dark background
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"primary_colour": "#1D4ED8"},
        )

    assert response.status_code == 200
    assert response.json()["primary_colour"] == "#1D4ED8"


# ---------------------------------------------------------------------------
# AC3 — PUT /settings/dojo rejects primary_colour that fails WCAG AA contrast
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_dojo_settings_rejects_low_contrast_colour(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """PUT /settings/dojo rejects a primary_colour failing WCAG 2.1 AA (4.5:1) against white."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # #FFD700 (yellow) fails 4.5:1 against white
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"primary_colour": "#FFD700"},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_dojo_settings_rejects_colour_failing_against_dark_bg(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """PUT /settings/dojo rejects a colour failing 4.5:1 against the dark background."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # Very light colour: near-white fails against dark background (#1A1A1A)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"primary_colour": "#F0F0F0"},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC4 — PUT /settings/dojo is admin-only (member token → 403)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_dojo_settings_member_returns_403(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A member token must receive 403 from PUT /settings/dojo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"dojo_name": "Hacked Dojo"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_put_dojo_settings_unauthenticated_returns_401(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """No token must receive 401 from PUT /settings/dojo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put("/settings/dojo", json={"dojo_name": "Any"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC5 — POST /settings/logo is admin-only (member token → 403)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_settings_logo_member_returns_403() -> None:
    """A member token must receive 403 from POST /settings/logo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_post_settings_logo_unauthenticated_returns_401() -> None:
    """No token must receive 401 from POST /settings/logo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
        )

    assert response.status_code == 401
