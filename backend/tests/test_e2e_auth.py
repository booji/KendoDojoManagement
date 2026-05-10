"""
E2E browser tests for issue #3 — email/password auth.

Acceptance criteria:
  1. POST /auth/register/password creates a new account with hashed password
  2. POST /auth/login/password returns a JWT (cookie) on valid credentials, 401 on invalid
  3. Protected endpoints return 401 when no valid token is provided
  4. Deactivated accounts cannot log in
  5. Login and register UI pages exist and are functional
  6. Passwords are never stored in plaintext

Criteria 1, 2, 3, 4, 6 are covered by unit/integration tests in test_auth.py.
This file covers criterion 5 via browser tests, plus smoke-checks for the UI
pages themselves.
"""

import uuid

from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"


# ── Register page ─────────────────────────────────────────────────────────────


def test_register_page_renders(page: Page) -> None:
    """The /register route renders passkey mode by default; password mode shows on toggle."""
    page.goto(f"{BASE_URL}/register")
    expect(page.get_by_label("Email")).to_be_visible()
    # Switch to password mode to verify those fields exist
    page.get_by_role("button", name="Use email and password instead").click()
    expect(page.get_by_label("Password", exact=True)).to_be_visible()
    expect(page.get_by_label("Confirm password")).to_be_visible()
    expect(page.get_by_role("button", name="Register")).to_be_visible()


def test_register_flow_redirects_to_login(page: Page) -> None:
    """Filling the register form with valid data submits and redirects to /login."""
    page.goto(f"{BASE_URL}/register")
    page.get_by_role("button", name="Use email and password instead").click()
    page.get_by_label("Email").fill(f"e2e_register_{uuid.uuid4().hex[:8]}@dojo.test")
    page.get_by_label("Password", exact=True).fill("Str0ng!Pass")
    page.get_by_label("Confirm password").fill("Str0ng!Pass")
    page.get_by_role("button", name="Register").click()
    expect(page).to_have_url(f"{BASE_URL}/login")


# ── Login page ────────────────────────────────────────────────────────────────


def test_login_page_renders(page: Page) -> None:
    """The /login route renders passkey mode by default; password mode shows on toggle."""
    page.goto(f"{BASE_URL}/login")
    expect(page.get_by_label("Email")).to_be_visible()
    page.get_by_role("button", name="Use email and password instead").click()
    expect(page.get_by_label("Password")).to_be_visible()
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()


def test_login_flow_redirects_to_home(page: Page) -> None:
    """Logging in with valid credentials redirects to /."""
    email = f"e2e_login_{uuid.uuid4().hex[:8]}@dojo.test"

    # Register first
    page.goto(f"{BASE_URL}/register")
    page.get_by_role("button", name="Use email and password instead").click()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill("Str0ng!Pass")
    page.get_by_label("Confirm password").fill("Str0ng!Pass")
    page.get_by_role("button", name="Register").click()
    expect(page).to_have_url(f"{BASE_URL}/login")

    # Now log in
    page.get_by_role("button", name="Use email and password instead").click()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill("Str0ng!Pass")
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE_URL}/")


# ── Unauthenticated redirect ──────────────────────────────────────────────────


def test_home_redirects_unauthenticated_to_login(page: Page) -> None:
    """Navigating to / without a session redirects to /login."""
    # Clear any cookies left from other tests
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/")
    expect(page).to_have_url(f"{BASE_URL}/login")
