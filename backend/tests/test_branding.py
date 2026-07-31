"""
Unit/integration tests for issue #213 — Customisable login screen branding.

Uses StubRepository pattern — NO real DB.

Acceptance criteria covered here:
  2. GET /settings/branding is reachable with NO authentication and returns the
     gated public projection. Hidden assets/name never appear for anonymous
     callers.
  3. POST /settings/background is admin-only. MIME whitelist png/jpeg/webp/gif
     + extension check; rejects non-image type (422); rejects files over the
     5 MB cap (422); on success persists background_image_url served under
     /static/backgrounds/.
  4. PUT /settings/dojo accepts background_image_url (nullable; null removes
     the background) and the three booleans login_show_background,
     login_show_logo, login_show_name, alongside existing fields. Verify they
     persist and that setting background_image_url to null clears it.
  5. GET /settings/dojo is member-only and returns the new RAW fields
     (background_image_url + the three toggles) regardless of toggle state.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app
from app.settings.dependencies import get_dojo_settings_repo
from app.settings.repository import StubDojoSettingsRepository

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid-branding", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid-branding", email="member@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


def _member_token() -> str:
    return encode_token(_MEMBER)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepository:
    repo = StubDojoSettingsRepository()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC2 — GET /settings/branding reachable with NO authentication
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_branding_reachable_without_authentication(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """GET /settings/branding requires no auth cookie/token at all."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/branding")

    assert response.status_code == 200


@pytest.mark.anyio
async def test_get_branding_always_includes_primary_colour(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """primary_colour is always present in the public branding response."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/branding")

    assert response.status_code == 200
    body = response.json()
    assert "primary_colour" in body
    assert body["primary_colour"]


@pytest.mark.anyio
async def test_get_branding_hides_dojo_name_when_login_show_name_off(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """dojo_name never appears for anonymous callers when login_show_name is off."""
    await settings_repo.update({"dojo_name": "Secret Dojo", "login_show_name": False})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/branding")

    assert response.status_code == 200
    body = response.json()
    assert body.get("dojo_name") is None
    assert "Secret Dojo" not in response.text


@pytest.mark.anyio
async def test_get_branding_hides_logo_when_login_show_logo_off(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """logo_url never appears for anonymous callers when login_show_logo is off."""
    await settings_repo.update(
        {"logo_url": "/static/logos/secret.png", "login_show_logo": False}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/branding")

    assert response.status_code == 200
    body = response.json()
    assert body.get("logo_url") is None
    assert "secret.png" not in response.text


@pytest.mark.anyio
async def test_get_branding_hides_background_when_login_show_background_off(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """background_image_url never appears for anonymous callers when the toggle is off."""
    await settings_repo.update(
        {
            "background_image_url": "/static/backgrounds/secret.jpg",
            "login_show_background": False,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/branding")

    assert response.status_code == 200
    body = response.json()
    assert body.get("background_image_url") is None
    assert "secret.jpg" not in response.text


@pytest.mark.anyio
async def test_get_branding_shows_assets_when_toggles_on(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """Enabled toggles surface the corresponding assets/name to anonymous callers."""
    await settings_repo.update(
        {
            "dojo_name": "Public Dojo",
            "logo_url": "/static/logos/public.png",
            "background_image_url": "/static/backgrounds/public.jpg",
            "login_show_name": True,
            "login_show_logo": True,
            "login_show_background": True,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/branding")

    assert response.status_code == 200
    body = response.json()
    assert body["dojo_name"] == "Public Dojo"
    assert body["logo_url"] == "/static/logos/public.png"
    assert body["background_image_url"] == "/static/backgrounds/public.jpg"


# ---------------------------------------------------------------------------
# AC3 — POST /settings/background is admin-only, MIME/ext/size validated
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_background_member_returns_403(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A member token must receive 403 from POST /settings/background."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.png", b"fake-png-bytes", "image/png")},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_post_background_unauthenticated_returns_401(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """No token must receive 401 from POST /settings/background."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.png", b"fake-png-bytes", "image/png")},
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_post_background_rejects_non_image_mime_type(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A non-image MIME type (e.g. text/plain) is rejected with 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.txt", b"not an image", "text/plain")},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_post_background_accepts_png(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A valid PNG upload succeeds and persists background_image_url."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.png", b"fake-png-bytes", "image/png")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["background_image_url"].startswith("/static/backgrounds/")


@pytest.mark.anyio
async def test_post_background_accepts_jpeg(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A valid JPEG upload succeeds."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_post_background_accepts_webp(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A valid WEBP upload succeeds."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.webp", b"fake-webp-bytes", "image/webp")},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_post_background_accepts_gif(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A valid GIF upload succeeds."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.gif", b"fake-gif-bytes", "image/gif")},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_post_background_rejects_files_over_5mb_cap(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A file larger than the 5 MB cap is rejected with 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    oversized = b"0" * (5 * 1024 * 1024 + 1)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.png", oversized, "image/png")},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_post_background_accepts_file_at_exactly_5mb(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A file exactly at the 5 MB cap is accepted (only files OVER the cap reject)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    exactly_5mb = b"0" * (5 * 1024 * 1024)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/settings/background",
            files={"file": ("bg.png", exactly_5mb, "image/png")},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_post_background_success_persists_background_image_url(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A successful upload is visible on a subsequent GET /settings/dojo (member)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        upload_resp = await c.post(
            "/settings/background",
            files={"file": ("bg.png", b"fake-png-bytes", "image/png")},
        )
        get_resp = await c.get("/settings/dojo")

    assert upload_resp.status_code == 200
    assert get_resp.status_code == 200
    assert (
        get_resp.json()["background_image_url"]
        == upload_resp.json()["background_image_url"]
    )
    assert get_resp.json()["background_image_url"].startswith("/static/backgrounds/")


# ---------------------------------------------------------------------------
# AC4 — PUT /settings/dojo accepts background_image_url + toggles; null clears
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_dojo_settings_persists_login_show_name_toggle(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """PUT /settings/dojo persists login_show_name."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"login_show_name": False},
        )

    assert response.status_code == 200
    assert response.json()["login_show_name"] is False


@pytest.mark.anyio
async def test_put_dojo_settings_persists_login_show_logo_toggle(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """PUT /settings/dojo persists login_show_logo."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"login_show_logo": False},
        )

    assert response.status_code == 200
    assert response.json()["login_show_logo"] is False


@pytest.mark.anyio
async def test_put_dojo_settings_persists_login_show_background_toggle(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """PUT /settings/dojo persists login_show_background."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"login_show_background": True},
        )

    assert response.status_code == 200
    assert response.json()["login_show_background"] is True


@pytest.mark.anyio
async def test_put_dojo_settings_persists_background_image_url(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """PUT /settings/dojo persists a directly-set background_image_url."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"background_image_url": "/static/backgrounds/manual.png"},
        )

    assert response.status_code == 200
    assert response.json()["background_image_url"] == "/static/backgrounds/manual.png"


@pytest.mark.anyio
async def test_put_dojo_settings_null_background_image_url_clears_it(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """Passing background_image_url: null removes the previously-set background."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await settings_repo.update(
        {"background_image_url": "/static/backgrounds/existing.png"}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        put_resp = await c.put(
            "/settings/dojo",
            json={"background_image_url": None},
        )
        get_resp = await c.get("/settings/dojo")

    assert put_resp.status_code == 200
    assert put_resp.json()["background_image_url"] is None
    assert get_resp.json()["background_image_url"] is None


@pytest.mark.anyio
async def test_put_dojo_settings_toggles_member_returns_403(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """A member token must receive 403 attempting to set branding toggles."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"login_show_name": False},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC5 — GET /settings/dojo is member-only and returns RAW branding fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_dojo_settings_member_only(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """GET /settings/dojo requires at least member auth (401 with no token)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_get_dojo_settings_returns_raw_background_and_toggles(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """GET /settings/dojo returns background_image_url and all three toggles."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await settings_repo.update(
        {
            "background_image_url": "/static/backgrounds/raw.png",
            "login_show_name": False,
            "login_show_logo": False,
            "login_show_background": True,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 200
    body = response.json()
    assert body["background_image_url"] == "/static/backgrounds/raw.png"
    assert body["login_show_name"] is False
    assert body["login_show_logo"] is False
    assert body["login_show_background"] is True


@pytest.mark.anyio
async def test_get_dojo_settings_raw_fields_present_regardless_of_toggle_state(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """The raw admin view shows dojo_name/logo_url even when their toggles are off —
    unlike the gated public /settings/branding view."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await settings_repo.update(
        {
            "dojo_name": "Admin Visible Name",
            "logo_url": "/static/logos/admin-visible.png",
            "login_show_name": False,
            "login_show_logo": False,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 200
    body = response.json()
    assert body["dojo_name"] == "Admin Visible Name"
    assert body["logo_url"] == "/static/logos/admin-visible.png"


@pytest.mark.anyio
async def test_get_dojo_settings_default_toggles(
    settings_repo: StubDojoSettingsRepository,
) -> None:
    """Default toggle values are booleans present in the response with no prior update."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["login_show_name"], bool)
    assert isinstance(body["login_show_logo"], bool)
    assert isinstance(body["login_show_background"], bool)
    assert "background_image_url" in body
