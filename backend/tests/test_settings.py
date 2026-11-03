"""
Unit/integration tests for issue #12 — Dojo Settings (GET/PUT /settings/dojo, POST /settings/logo).

Uses StubRepository pattern — NO real DB.

Acceptance criteria covered here:
  1. GET /settings/dojo returns defaults when no settings saved
     (dojo_name="My Dojo", logo_url=None, primary_colour=default hex)
  2. PUT /settings/dojo persists dojo_name and primary_colour
  3. PUT /settings/dojo accepts any valid brand hue; the frontend derives
     per-theme AA-legible --primary shades from it (issue #223)
  4. PUT /settings/dojo is admin-only (member token → 403)
  5. POST /settings/logo is admin-only (member token → 403)
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.main import app
from tests.auth_support import sign_in
from tests.dojo_settings_support import StubDojoSettingsRepo

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")


def _admin_override():
    return _ADMIN


def _member_token() -> str:
    return sign_in(_MEMBER)


# The dojo settings stub lives in tests/dojo_settings_support.py so its shape
# stays in step with every other settings test (see issue #221).

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


async def test_get_dojo_settings_returns_defaults_when_none_saved(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """GET /settings/dojo returns the hardcoded defaults when the DB has no row."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
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


async def test_get_dojo_settings_unauthenticated_returns_401(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """GET /settings/dojo without a token returns 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC2 — PUT /settings/dojo persists dojo_name and primary_colour
# ---------------------------------------------------------------------------


async def test_put_dojo_settings_persists_dojo_name(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """PUT /settings/dojo with a new dojo_name returns the updated value."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"dojo_name": "Tokyo Kendo Club"},
        )

    assert response.status_code == 200
    assert response.json()["dojo_name"] == "Tokyo Kendo Club"


async def test_put_dojo_settings_dojo_name_visible_on_get(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """Updated dojo_name is visible on a subsequent GET /settings/dojo."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.put("/settings/dojo", json={"dojo_name": "Osaka Dojo"})
        get_resp = await c.get("/settings/dojo")

    assert get_resp.status_code == 200
    assert get_resp.json()["dojo_name"] == "Osaka Dojo"


async def test_put_dojo_settings_persists_primary_colour(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """PUT /settings/dojo with a WCAG-passing primary_colour persists the value."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # #1D4ED8 (blue-700) has >4.5:1 against white and dark background
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"primary_colour": "#1D4ED8"},
        )

    assert response.status_code == 200
    assert response.json()["primary_colour"] == "#1D4ED8"


# ---------------------------------------------------------------------------
# AC3 — brand hue is admissible regardless of its own contrast (issue #223)
# The frontend derives per-theme AA shades from the hue, so the raw colour no
# longer has to clear contrast against any single background.
# ---------------------------------------------------------------------------


async def test_put_dojo_settings_accepts_light_brand_hue(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A light hue (#FFD700), previously rejected vs white, is now accepted."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"primary_colour": "#FFD700"},
        )

    assert response.status_code == 200
    assert response.json()["primary_colour"] == "#FFD700"


async def test_put_dojo_settings_accepts_near_white_brand_hue(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A near-white hue (#F0F0F0), previously rejected vs the dark bg, is now accepted."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"primary_colour": "#F0F0F0"},
        )

    assert response.status_code == 200
    assert response.json()["primary_colour"] == "#F0F0F0"


# ---------------------------------------------------------------------------
# AC4 — PUT /settings/dojo is admin-only (member token → 403)
# ---------------------------------------------------------------------------


async def test_put_dojo_settings_member_returns_403(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A member token must receive 403 from PUT /settings/dojo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"dojo_name": "Hacked Dojo"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


async def test_put_dojo_settings_unauthenticated_returns_401(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """No token must receive 401 from PUT /settings/dojo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put("/settings/dojo", json={"dojo_name": "Any"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC5 — POST /settings/logo is admin-only (member token → 403)
# ---------------------------------------------------------------------------


async def test_post_settings_logo_member_returns_403() -> None:
    """A member token must receive 403 from POST /settings/logo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/settings/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


async def test_post_settings_logo_unauthenticated_returns_401() -> None:
    """No token must receive 401 from POST /settings/logo."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/settings/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Issue #240 — upload content is sniffed, not trusted
# ---------------------------------------------------------------------------

_REAL_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.mark.parametrize("endpoint", ["/settings/logo", "/settings/background"])
async def test_upload_rejects_payload_that_is_not_really_an_image(
    settings_repo: StubDojoSettingsRepo,
    endpoint: str,
) -> None:
    """A declared image/png with a non-image body must be rejected.

    content_type and filename are both attacker-controlled; only the bytes
    are evidence.
    """
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            endpoint,
            files={
                "file": (
                    "logo.png",
                    b"<html><script>alert(1)</script></html>",
                    "image/png",
                )
            },
        )

    assert response.status_code == 422
    assert "image" in response.json()["detail"].lower()


@pytest.mark.parametrize("endpoint", ["/settings/logo", "/settings/background"])
async def test_upload_rejects_sniffed_type_outside_allowed_set(
    settings_repo: StubDojoSettingsRepo,
    endpoint: str,
) -> None:
    """An SVG renamed to .png must not slip through — SVG can carry script."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            endpoint,
            files={
                "file": (
                    "logo.png",
                    b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
                    "image/png",
                )
            },
        )

    assert response.status_code == 422


async def test_upload_accepts_a_genuine_png(
    settings_repo: StubDojoSettingsRepo,
    tmp_path,
    monkeypatch,
) -> None:
    """The happy path still works once sniffing is in place."""
    monkeypatch.setattr("app.settings.router._STATIC_DIR", str(tmp_path))
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/settings/logo",
            files={"file": ("logo.png", _REAL_PNG, "image/png")},
        )

    assert response.status_code == 200
    assert response.json()["logo_url"].startswith("/static/logos/")


# ---------------------------------------------------------------------------
# Issue #556 — an Admin can see which Version is running
# ---------------------------------------------------------------------------


async def test_admin_gets_the_version_the_image_was_built_with(monkeypatch) -> None:
    monkeypatch.setenv("KENDO_VERSION", "0.1.5")
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/settings/version")

    assert response.status_code == 200
    assert response.json() == {"version": "0.1.5"}


async def test_a_build_that_is_not_a_release_reports_dev(monkeypatch) -> None:
    monkeypatch.delenv("KENDO_VERSION", raising=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/settings/version")

    assert response.json() == {"version": "dev"}


async def test_an_image_built_without_a_version_reports_dev(monkeypatch) -> None:
    # The Dockerfile's KENDO_VERSION build arg defaults to empty.
    monkeypatch.setenv("KENDO_VERSION", "")
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/settings/version")

    assert response.json() == {"version": "dev"}


async def test_a_member_cannot_get_the_version() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/settings/version", cookies={"access_token": _member_token()}
        )

    assert response.status_code == 403


async def test_a_signed_out_request_cannot_get_the_version() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/settings/version")

    assert response.status_code == 401
