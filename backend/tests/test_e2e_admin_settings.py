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

import pathlib
import sqlite3 as _sqlite3
import uuid

import pytest
import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

# Path to the dev SQLite DB used by the running server
_DB_PATH = pathlib.Path(__file__).parent.parent / "kendo.db"


# ── helpers ────────────────────────────────────────────────────────────────


def _register_api(email: str, password: str = "Str0ng!Pass") -> str:
    resp = requests.post(
        f"{API_URL}/auth/register/password",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["sub"]


def _login_api(email: str, password: str = "Str0ng!Pass") -> str:
    resp = requests.post(
        f"{API_URL}/auth/login/password",
        json={"email": email, "password": password},
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


def _promote_to_admin(user_id: str) -> None:
    """Directly set a user's role to admin in the local SQLite dev DB."""
    with _sqlite3.connect(_DB_PATH) as conn:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))


def _register_admin_user() -> str:
    """Register a fresh user, promote them to admin, return their access token."""
    tag = uuid.uuid4().hex[:8]
    email = f"e2e_admin_{tag}@dojo.test"
    user_id = _register_api(email)
    _promote_to_admin(user_id)
    return _login_api(email)


def _register_member_user() -> str:
    """Register a fresh regular member, return their access token."""
    tag = uuid.uuid4().hex[:8]
    email = f"e2e_member_{tag}@dojo.test"
    _register_api(email)
    return _login_api(email)


# ── AC6 — Admin nav renders both Settings and Admin Settings links ─────────


def test_admin_nav_has_settings_and_admin_settings_links(page: Page) -> None:
    token = _register_admin_user()
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
    token = _register_admin_user()
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC8 — /admin/settings renders Admin Settings page ─────────────────────


def test_admin_settings_page_renders_non_blank_content(page: Page) -> None:
    token = _register_admin_user()
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_role("heading", name="Admin Settings")).to_be_visible()


# ── AC9 — /admin/settings is not accessible to a regular member ───────────


def test_admin_settings_page_redirects_regular_member(page: Page) -> None:
    member_token = _register_member_user()
    _inject_cookie(page, member_token)

    page.goto(f"{BASE_URL}/admin/settings")

    # RequireAdmin guard redirects non-admins to /
    expect(page).not_to_have_url(f"{BASE_URL}/admin/settings")
