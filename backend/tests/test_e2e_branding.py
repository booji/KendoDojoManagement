"""
E2E browser tests for issue #213 — Customisable login screen branding.

Acceptance criteria exercised here (user-facing):
  - Login page shows dojo name/logo/background when their toggles are on
  - Login page shows a bare card (no name/logo/background) when all toggles
    are off
  - Admin Settings has a "Login Screen" subsection with auto-saving toggles
  - Admin Settings "Login Screen" subsection supports background upload
  - Admin Settings "Login Screen" subsection supports background removal
"""

import re
import uuid

import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"

# Uploads are content-sniffed (#240), so the payload must really be a PNG.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


# ── helpers ───────────────────────────────────────────────────────────────


def _login_admin() -> str:
    """Register/login a fresh admin via the test-only auth endpoint and
    return the access_token cookie value."""
    email = f"branding_{uuid.uuid4().hex[:8]}@dojo.test"
    resp = requests.post(
        f"{API_URL}/auth/login/test", json={"email": email, "role": "admin"}
    )
    resp.raise_for_status()
    return resp.cookies["access_token"]


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ]
    )


def _update_dojo_settings(token: str, **payload) -> dict:
    resp = requests.put(
        f"{API_URL}/settings/dojo", json=payload, cookies={"access_token": token}
    )
    resp.raise_for_status()
    return resp.json()


def _upload_background(token: str) -> str:
    resp = requests.post(
        f"{API_URL}/settings/background",
        files={"file": ("bg.png", _PNG_BYTES, "image/png")},
        cookies={"access_token": token},
    )
    resp.raise_for_status()
    return resp.json()["background_image_url"]


def _upload_logo(token: str) -> str:
    resp = requests.post(
        f"{API_URL}/settings/logo",
        files={"file": ("logo.png", _PNG_BYTES, "image/png")},
        cookies={"access_token": token},
    )
    resp.raise_for_status()
    return resp.json()["logo_url"]


def _complete_onboarding(token: str) -> None:
    """Give the admin a Member record so the app's onboarding guard doesn't
    redirect /admin/settings visits to /onboarding."""
    resp = requests.put(
        f"{API_URL}/accounts/me/member",
        json={
            "first_name": "Admin",
            "surname": "User",
            "dob": "1990-01-01",
        },
        cookies={"access_token": token},
    )
    resp.raise_for_status()


# ── Login page shows dojo name when login_show_name is on ─────────────────


def test_login_page_shows_dojo_name_when_login_show_name_on(page: Page) -> None:
    """Login page renders the configured dojo name when login_show_name is enabled."""
    token = _login_admin()
    dojo_name = f"Test Dojo {uuid.uuid4().hex[:6]}"
    _update_dojo_settings(
        token,
        dojo_name=dojo_name,
        login_show_name=True,
        login_show_logo=False,
        login_show_background=False,
    )

    page.goto(f"{BASE_URL}/login")

    expect(page.get_by_role("heading", name=dojo_name)).to_be_visible()


# ── Login page shows logo when login_show_logo is on ───────────────────────


def test_login_page_shows_logo_when_login_show_logo_on(page: Page) -> None:
    """Login page renders the configured logo image when login_show_logo is enabled."""
    token = _login_admin()
    _upload_logo(token)
    _update_dojo_settings(
        token,
        login_show_name=False,
        login_show_logo=True,
        login_show_background=False,
    )

    page.goto(f"{BASE_URL}/login")

    expect(page.get_by_alt_text("Dojo logo")).to_be_visible()


# ── Login page shows background when login_show_background is on ─────────


def test_login_page_shows_background_when_login_show_background_on(
    page: Page,
) -> None:
    """Login page renders the configured background image (with a scrim) when
    login_show_background is enabled."""
    token = _login_admin()
    background_url = _upload_background(token)
    _update_dojo_settings(
        token,
        login_show_name=False,
        login_show_logo=False,
        login_show_background=True,
    )

    page.goto(f"{BASE_URL}/login")

    background_layer = page.locator("div.fixed.inset-0.-z-20")
    expect(background_layer).to_be_attached()
    style = background_layer.get_attribute("style") or ""
    assert background_url in style, f"expected background url in style, got: {style}"

    # Scrim overlay sits above the background image
    scrim = page.locator("div.fixed.inset-0.-z-10")
    expect(scrim).to_be_attached()


# ── Login page shows bare card when all branding toggles are off ──────────


def test_login_page_shows_bare_card_when_all_branding_toggles_off(
    page: Page,
) -> None:
    """When login_show_name, login_show_logo, and login_show_background are all
    off, the login page renders a bare card with no dojo name, logo, or
    background image — only the login form itself."""
    token = _login_admin()
    _update_dojo_settings(
        token,
        login_show_name=False,
        login_show_logo=False,
        login_show_background=False,
    )

    page.goto(f"{BASE_URL}/login")

    # The login form itself is present
    expect(page.get_by_role("button", name="Sign in with passkey")).to_be_visible()

    # No dojo name heading, no logo image, no background layer
    expect(page.locator("h1")).to_have_count(0)
    expect(page.get_by_alt_text("Dojo logo")).to_have_count(0)
    expect(page.locator("div.fixed.inset-0.-z-20")).to_have_count(0)


# ── Admin Settings has a "Login Screen" subsection ─────────────────────────


def test_admin_settings_has_login_screen_subsection(page: Page) -> None:
    """Admin Settings page renders a 'Login Screen' subsection distinct from
    the general Appearance/Dojo settings, containing the branding toggles."""
    token = _login_admin()
    _complete_onboarding(token)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_role("heading", name="Login Screen")).to_be_visible()
    expect(page.locator("#login-show-background")).to_be_visible()
    expect(page.locator("#login-show-logo")).to_be_visible()
    expect(page.locator("#login-show-name")).to_be_visible()


# ── Login Screen toggles auto-save and persist ─────────────────────────────


def test_admin_settings_login_screen_toggles_auto_save(page: Page) -> None:
    """Toggling 'Show dojo name' in the Login Screen subsection saves
    immediately without a separate Save button, and the new state persists
    after a page reload."""
    token = _login_admin()
    _update_dojo_settings(token, login_show_name=False)
    _complete_onboarding(token)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    toggle = page.locator("#login-show-name")
    expect(toggle).not_to_be_checked()

    # The id is on Base UI's hidden input; flip the toggle via its label.
    page.locator('label[for="login-show-name"]').click()
    expect(toggle).to_be_checked()

    # Auto-saved without a page action — confirm against the backend directly
    resp = requests.get(f"{API_URL}/settings/dojo", cookies={"access_token": token})
    resp.raise_for_status()
    assert resp.json()["login_show_name"] is True

    # And it survives a reload of the page
    page.reload()
    expect(page.locator("#login-show-name")).to_be_checked()


# ── Login Screen background upload ─────────────────────────────────────────


def test_admin_settings_login_screen_background_upload(page: Page) -> None:
    """Admin can upload a background image from the Login Screen subsection;
    on success the preview updates to show the newly uploaded image."""
    token = _login_admin()
    _update_dojo_settings(token, background_image_url=None)
    _complete_onboarding(token)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_alt_text("Login background preview")).to_have_count(0)

    page.locator("#background-upload").set_input_files(
        {
            "name": "background.png",
            "mimeType": "image/png",
            "buffer": _PNG_BYTES,
        }
    )

    preview = page.get_by_alt_text("Login background preview")
    # The component shows a local blob: preview immediately and only swaps in
    # the server URL once the upload resolves, so sampling src right away
    # races the round-trip. to_have_attribute retries until the swap lands.
    expect(preview).to_be_visible()
    expect(preview).to_have_attribute("src", re.compile(r"/static/backgrounds/"))

    # Confirm the backend actually stored it
    resp = requests.get(f"{API_URL}/settings/dojo", cookies={"access_token": token})
    resp.raise_for_status()
    assert resp.json()["background_image_url"] is not None


# ── Login Screen background remove ─────────────────────────────────────────


def test_admin_settings_login_screen_background_remove(page: Page) -> None:
    """Admin can remove a previously uploaded background image via a 'Remove'
    action in the Login Screen subsection; the preview reverts to the empty
    state and the login page no longer shows a background."""
    token = _login_admin()
    _upload_background(token)
    _complete_onboarding(token)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_alt_text("Login background preview")).to_be_visible()

    page.get_by_role("button", name="Remove login screen background").click()

    expect(page.get_by_alt_text("Login background preview")).to_have_count(0)

    # Persisted server-side
    resp = requests.get(f"{API_URL}/settings/dojo", cookies={"access_token": token})
    resp.raise_for_status()
    assert resp.json()["background_image_url"] is None

    # Login page no longer shows a background, even if the toggle were on
    _update_dojo_settings(token, login_show_background=True)
    page.goto(f"{BASE_URL}/login")
    expect(page.locator("div.fixed.inset-0.-z-20")).to_have_count(0)
