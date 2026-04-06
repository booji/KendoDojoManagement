"""E2E tests for passkey UI visibility on the register and login pages."""

from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"


def test_e2e_passkey_register_button_visible(page: Page) -> None:
    """Register page should show a passkey option as the primary action."""
    page.goto(f"{BASE_URL}/register")
    expect(page.get_by_role("button", name="Register with passkey")).to_be_visible()


def test_e2e_passkey_login_button_visible(page: Page) -> None:
    """Login page should show a passkey option as the primary action."""
    page.goto(f"{BASE_URL}/login")
    expect(page.get_by_role("button", name="Sign in with passkey")).to_be_visible()
