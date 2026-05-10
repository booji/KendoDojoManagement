"""
Playwright browser tests for issue #45 — Admin Personal Settings parity.

Acceptance criteria covered here (criteria 6-9):
  6. The admin nav renders both a "Settings" link (href=/settings) and an
     "Admin Settings" link (href=/admin/settings).
  7. Visiting /settings as an admin renders the Personal Details view/edit UI
     (not a blank stub).
  8. Visiting /admin/settings as an admin renders the Admin Settings page
     (any non-blank content or heading).
  9. Visiting /admin/settings as a regular member is redirected (not accessible).
"""

import os
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"


# ── helpers ────────────────────────────────────────────────────────────────


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _inject_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


# ── AC6 — Admin nav renders both Settings and Admin Settings links ─────────


def test_admin_nav_has_settings_and_admin_settings_links(page: Page) -> None:
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/")

    # Personal Settings link → /settings
    settings_link = page.get_by_role("link", name="Settings", exact=True)
    expect(settings_link).to_be_visible()
    expect(settings_link).to_have_attribute("href", "/settings")

    # Admin Settings link → /admin/settings
    admin_settings_link = page.get_by_role("link", name="Admin Settings")
    expect(admin_settings_link).to_be_visible()
    expect(admin_settings_link).to_have_attribute("href", "/admin/settings")


# ── AC7 — /settings as admin renders Personal Details UI ──────────────────


def test_admin_settings_page_renders_personal_details(page: Page) -> None:
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC8 — /admin/settings renders Admin Settings page ─────────────────────


def test_admin_settings_page_renders_non_blank_content(page: Page) -> None:
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_role("heading", name="Admin Settings")).to_be_visible()


# ── AC9 — /admin/settings is not accessible to a regular member ───────────


def test_admin_settings_page_redirects_regular_member(page: Page) -> None:
    token = _make_token("member")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    # RequireAdmin guard redirects non-admins to /
    expect(page).not_to_have_url(f"{BASE_URL}/admin/settings")
