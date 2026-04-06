"""
Playwright browser tests for issue #27 — Settings page: Personal Details.

Acceptance criteria:
  1. /settings shows a Personal Details section with fields: full name, date of birth,
     emergency contact name, emergency contact phone, federation number
  2. Fields are pre-populated with the user's current Member record values on load
  3. Saving a change updates the value and shows a success confirmation
  4. A backend error surfaces as an inline error message (no silent failures)
  5. If the user has no linked Member record yet, fields are empty and saving creates it
  6. /profile redirects to /settings
  7. Layout is usable on mobile and desktop
  8. E2E: user edits their name, saves, reloads — updated name persists
"""

import uuid

import requests
from playwright.sync_api import Page, Route, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ── helpers ───────────────────────────────────────────────────────────────────


def _register_api(email: str, password: str = "Str0ng!Pass") -> str:
    """Register a user via the backend API, return user id."""
    resp = requests.post(
        f"{API_URL}/auth/register/password",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["sub"]


def _login_api(email: str, password: str = "Str0ng!Pass") -> str:
    """Log in via the backend API and return the access_token cookie value."""
    resp = requests.post(
        f"{API_URL}/auth/login/password",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.cookies["access_token"]


def _inject_cookie(page: Page, token: str) -> None:
    """Inject an access_token cookie into the Playwright browser context."""
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


def _create_member_record(
    token: str,
    full_name: str = "Alice Kendo",
    emergency_contact_name: str = "Bob Kendo",
    emergency_contact_phone: str = "07700900000",
    federation_number: str = "FED-001",
) -> dict:
    """Create or update a member record for the logged-in user via the backend API."""
    resp = requests.put(
        f"{API_URL}/users/me/member",
        json={
            "full_name": full_name,
            "dob": "1990-05-15",
            "emergency_contact_name": emergency_contact_name,
            "emergency_contact_phone": emergency_contact_phone,
            "federation_number": federation_number,
        },
        cookies={"access_token": token},
    )
    resp.raise_for_status()
    return resp.json()


# CardTitle renders as a <div>, not a semantic heading.
# The save button has aria-label="Save personal details" (not its visible text).
SAVE_BTN_NAME = "Save personal details"


# ── AC1 — Personal Details section with expected fields ──────────────────────


def test_settings_shows_personal_details_section(page: Page) -> None:
    email = f"ac1_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/settings")

    # Page heading
    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    # Card title (renders as div, not heading)
    expect(page.get_by_text("Personal Details")).to_be_visible()
    # Form fields
    expect(page.get_by_label("Full name")).to_be_visible()
    expect(page.get_by_label("Date of birth")).to_be_visible()
    expect(page.get_by_label("Emergency contact name")).to_be_visible()
    expect(page.get_by_label("Emergency contact phone")).to_be_visible()
    expect(page.get_by_label("Federation number")).to_be_visible()
    # Save button (aria-label differs from visible text)
    expect(page.get_by_role("button", name=SAVE_BTN_NAME)).to_be_visible()


# ── AC2 — Fields pre-populated from existing Member record ───────────────────


def test_settings_fields_prepopulated_from_member_record(page: Page) -> None:
    email = f"ac2_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Prepop Tester")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Wait for the form to be loaded and populated from the API
    expect(page.get_by_label("Full name")).to_have_value("Prepop Tester")
    expect(page.get_by_label("Emergency contact name")).to_have_value("Bob Kendo")
    expect(page.get_by_label("Emergency contact phone")).to_have_value("07700900000")
    expect(page.get_by_label("Federation number")).to_have_value("FED-001")


# ── AC3 — Saving a change shows success confirmation ─────────────────────────


def test_settings_save_shows_success_confirmation(page: Page) -> None:
    email = f"ac3_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Original Name")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Wait for the form to fully load
    full_name_input = page.get_by_label("Full name")
    expect(full_name_input).to_have_value("Original Name")

    full_name_input.fill("Updated Name")
    page.get_by_role("button", name=SAVE_BTN_NAME).click()

    expect(page.get_by_text("Details saved successfully.")).to_be_visible()


# ── AC4 — Backend error surfaces as inline error message ─────────────────────


def test_settings_backend_error_shows_inline_message(page: Page) -> None:
    email = f"ac4_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Error Tester")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Wait for the form to load
    expect(page.get_by_label("Full name")).to_have_value("Error Tester")

    # Intercept the PUT request to simulate a backend error
    def handle_route(route: Route) -> None:
        route.fulfill(
            status=500,
            content_type="application/json",
            body='{"detail": "Internal server error"}',
        )

    page.route("**/api/users/me/member", handle_route, times=1)

    page.get_by_label("Full name").fill("Will Fail")
    page.get_by_role("button", name=SAVE_BTN_NAME).click()

    # Error message should appear (role=alert)
    error = page.get_by_role("alert")
    expect(error).to_be_visible()
    # It should NOT show success
    expect(page.get_by_text("Details saved successfully.")).not_to_be_visible()


# ── AC5 — No Member record yet: empty fields, save creates the record ─────────


def test_settings_empty_fields_when_no_member_record(page: Page) -> None:
    email = f"ac5_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Wait for load to complete (save button appears once ready)
    expect(page.get_by_role("button", name=SAVE_BTN_NAME)).to_be_visible()

    # All fields should be empty — no member record linked
    expect(page.get_by_label("Full name")).to_have_value("")
    expect(page.get_by_label("Emergency contact name")).to_have_value("")
    expect(page.get_by_label("Emergency contact phone")).to_have_value("")
    expect(page.get_by_label("Federation number")).to_have_value("")

    # Save with a name to create the member record
    page.get_by_label("Full name").fill("New Member")
    page.get_by_role("button", name=SAVE_BTN_NAME).click()

    # Success message should appear, confirming creation
    expect(page.get_by_text("Details saved successfully.")).to_be_visible()


# ── AC6 — /profile redirects to /settings ────────────────────────────────────


def test_profile_redirects_to_settings(page: Page) -> None:
    email = f"ac6_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/profile")

    expect(page).to_have_url(f"{BASE_URL}/settings")
    # The settings page should render with Personal Details
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC7 — Layout usable on mobile ────────────────────────────────────────────


def test_settings_layout_usable_on_mobile(page: Page) -> None:
    page.set_viewport_size({"width": 375, "height": 667})
    email = f"ac7m_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Key form elements must be visible and not clipped
    expect(page.get_by_label("Full name")).to_be_visible()
    expect(page.get_by_label("Emergency contact name")).to_be_visible()

    save_btn = page.get_by_role("button", name=SAVE_BTN_NAME)
    expect(save_btn).to_be_visible()

    # On mobile the save button should span most of the viewport width
    box = save_btn.bounding_box()
    assert box is not None
    assert box["width"] > 200  # Full width on mobile (375px viewport)


# ── AC7 — Layout usable on desktop ───────────────────────────────────────────


def test_settings_layout_usable_on_desktop(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    email = f"ac7d_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Settings heading visible
    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    # Card title visible
    expect(page.get_by_text("Personal Details")).to_be_visible()
    # Form fields visible
    expect(page.get_by_label("Full name")).to_be_visible()
    expect(page.get_by_role("button", name=SAVE_BTN_NAME)).to_be_visible()


# ── AC8 — Edit name, save, reload: updated name persists ─────────────────────


def test_settings_edit_name_persists_after_reload(page: Page) -> None:
    email = f"ac8_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Before Reload")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    full_name_input = page.get_by_label("Full name")
    expect(full_name_input).to_have_value("Before Reload")

    full_name_input.fill("After Reload")
    page.get_by_role("button", name=SAVE_BTN_NAME).click()
    expect(page.get_by_text("Details saved successfully.")).to_be_visible()

    # Reload — cookie persists in browser context, so auth is retained
    page.reload()

    expect(page.get_by_label("Full name")).to_have_value("After Reload")
