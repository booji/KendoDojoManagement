"""
E2E browser tests for auth UI (issues #3 and #155).

Issue #3 — email/password auth criteria covered by unit/integration tests in test_auth.py.
Issue #155 — legacy password auth removal:
  - Login page must show only passkey form; no "Use email and password instead" option.
  - Register page must show only passkey form; no "Use email and password instead" option.

Criteria still covered by browser tests:
  - Unauthenticated redirect to /login
"""

import uuid

import pytest
import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Module fixture: seed a user so setup is unavailable and / → /login works
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _seeded_db() -> None:
    """Register a throwaway password user so the backend reports a populated instance.

    Without at least one user the backend's /setup endpoint returns 200, and the
    frontend redirects unauthenticated visitors from / to /setup instead of /login.
    This fixture seeds the DB once per module so all tests in this file observe
    the "populated" state.
    """
    email = f"e2e_auth_seed_{uuid.uuid4().hex[:8]}@dojo.test"
    resp = requests.post(
        f"{API_URL}/auth/login/test",
        json={"email": email, "role": "admin"},
        timeout=5,
    )
    assert resp.ok, f"Seed login failed: {resp.status_code} {resp.text}"


# ── Register page — passkey-only (issue #155) ─────────────────────────────────


def test_register_page_has_no_password_toggle(page: Page) -> None:
    """Register page must NOT show a 'Use email and password instead' button (AC2 issue #155)."""
    page.goto(f"{BASE_URL}/register")
    expect(page.get_by_text("Use email and password instead")).not_to_be_visible()


def test_register_page_renders_passkey_form_only(page: Page) -> None:
    """Register page shows the passkey form and no password fields (AC2 issue #155)."""
    page.goto(f"{BASE_URL}/register")
    expect(page.locator("input[type='password']")).to_have_count(0)


# ── Login page — passkey-only (issue #155) ────────────────────────────────────


def test_login_page_has_no_password_toggle(page: Page) -> None:
    """Login page must NOT show a 'Use email and password instead' button (AC1 issue #155)."""
    page.goto(f"{BASE_URL}/login")
    expect(page.get_by_text("Use email and password instead")).not_to_be_visible()


def test_login_page_renders_passkey_form_only(page: Page) -> None:
    """Login page shows the passkey form and no password fields (AC1 issue #155)."""
    page.goto(f"{BASE_URL}/login")
    expect(page.locator("input[type='password']")).to_have_count(0)


# ── Unauthenticated redirect ──────────────────────────────────────────────────


def test_home_redirects_unauthenticated_to_login(page: Page) -> None:
    """Navigating to / without a session redirects to /login."""
    # Clear any cookies left from other tests
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/")
    expect(page).to_have_url(f"{BASE_URL}/login")
