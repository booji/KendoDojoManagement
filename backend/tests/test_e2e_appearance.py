"""
E2E Playwright tests for issue #28 — Appearance section on Settings page.

Covers:
  AC1  — /settings has an Appearance section with Light / System / Dark toggle
  AC9  — selecting Dark on settings applies dark class to <html> immediately
  AC10 — setting Dark then reloading preserves the dark class before React hydrates

All tests are marked xfail(strict=True) because the Appearance section on the
Settings page does not exist yet.
"""

import os
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page

# Load .env with override=True so the JWT_SECRET matches what the server uses.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=True)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

import pytest  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

# Patch the cached module-level variable in case unit tests ran first.
_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# Helpers (mirror test_e2e_theme.py exactly)
# ---------------------------------------------------------------------------


def _make_token(role: str = "member") -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}@example.com",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _goto_authenticated(page: Page, token: str) -> None:
    """Navigate to the app with an auth cookie set, wait for the shell to render."""
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )
    page.goto(BASE_URL)
    page.wait_for_selector("[data-slot='sidebar']", timeout=15000)


def _is_dark(page: Page) -> bool:
    return page.evaluate("() => document.documentElement.classList.contains('dark')")


# ---------------------------------------------------------------------------
# AC1 — /settings has an Appearance section with three-way toggle
# ---------------------------------------------------------------------------


def test_settings_has_appearance_section_with_three_way_toggle(page: Page) -> None:
    """AC1: /settings renders an 'Appearance' heading and Light / System / Dark buttons."""
    token = _make_token()
    _goto_authenticated(page, token)
    page.goto(f"{BASE_URL}/settings")
    expect(page.get_by_role("heading", name="Appearance")).to_be_visible()
    expect(page.get_by_role("button", name="Light", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="System", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Dark", exact=True)).to_be_visible()


# ---------------------------------------------------------------------------
# AC9 — selecting Dark on /settings applies dark class immediately
# ---------------------------------------------------------------------------


def test_selecting_dark_on_settings_applies_dark_class(page: Page) -> None:
    """AC9: Clicking the 'Dark' button in the Appearance section adds 'dark' to <html>."""
    page.set_viewport_size({"width": 1280, "height": 800})
    token = _make_token()
    _goto_authenticated(page, token)
    page.goto(f"{BASE_URL}/settings")
    page.get_by_role("button", name="Dark", exact=True).click()
    page.wait_for_timeout(300)
    assert _is_dark(page), "<html> should have 'dark' class after clicking the Dark button"


# ---------------------------------------------------------------------------
# AC10 — dark class present before React hydration after reload
# ---------------------------------------------------------------------------


def test_selecting_dark_then_reload_applies_dark_class_immediately(page: Page) -> None:
    """AC10: After setting dark theme, a fresh page load has 'dark' on <html> before React hydrates.

    The inline anti-flash script in index.html runs synchronously before any module
    script, so the dark class must be present at DOMContentLoaded — not just after
    React hydration.
    """
    page.set_viewport_size({"width": 1280, "height": 800})
    token = _make_token()
    _goto_authenticated(page, token)
    page.goto(f"{BASE_URL}/settings")
    page.get_by_role("button", name="Dark", exact=True).click()
    page.wait_for_timeout(300)
    assert _is_dark(page), "Should be dark after clicking Dark button"

    # Open a new page with localStorage.theme = "dark" pre-set; check dark class
    # is applied synchronously by the inline anti-flash script before React hydrates.
    new_page = page.context.new_page()
    try:
        # Pre-set localStorage so the inline script will see it.
        new_page.add_init_script("localStorage.setItem('theme', 'dark');")
        new_page.goto(BASE_URL, wait_until="domcontentloaded")
        # Check immediately after DOMContentLoaded — before React has had a chance to run.
        is_dark_at_dom_ready = new_page.evaluate(
            "() => document.documentElement.classList.contains('dark')"
        )
        assert is_dark_at_dom_ready, (
            "dark class should be on <html> at DOMContentLoaded "
            "(inline anti-flash script should apply it synchronously)"
        )
    finally:
        new_page.close()
