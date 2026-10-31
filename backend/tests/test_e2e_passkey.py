"""E2E tests for passkey UI visibility on the register and login pages."""

from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"


def test_e2e_register_page_asks_for_an_invite(page: Page) -> None:
    """Members join by invite only (#472): /register offers no registration
    and tells the visitor to ask their dojo for an invite."""
    page.goto(f"{BASE_URL}/register")
    expect(page.get_by_text("ask your dojo for an invite")).to_be_visible()
    expect(page.get_by_role("button", name="Register with passkey")).to_have_count(0)
    expect(page.locator("input[type='email']")).to_have_count(0)


def test_e2e_passkey_login_button_visible(page: Page) -> None:
    """Login page should show a passkey option as the primary action."""
    page.goto(f"{BASE_URL}/login")
    expect(page.get_by_role("button", name="Sign in with passkey")).to_be_visible()
