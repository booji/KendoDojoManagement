"""
Playwright browser tests for issue #27/#28 — Settings page: Personal Details.

Acceptance criteria:
  1. /settings shows a Personal Details section
  2. Summary shows the user's current Member record values on load
  3. Saving a change returns to the summary showing the updated values
  4. A backend error surfaces as an inline error message (no silent failures)
  5. If the user has no linked Member record yet, "Set up profile" button shown;
     saving creates the record
  6. /profile redirects to /settings
  7. Layout is usable on mobile and desktop
  8. E2E: user edits their name, saves, reloads — updated name persists
  9. /settings default view shows a read-only summary (not a form)
  10. Clicking "Edit" switches to the edit form
  11. Clicking "Cancel" returns to the read-only summary without saving
  12. Clicking "Save changes" saves and returns to the summary with updated values
"""

import uuid

import pytest
import requests
from playwright.sync_api import Page, Route, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ── helpers ───────────────────────────────────────────────────────────────────


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


def _create_member_record(
    token: str,
    full_name: str = "Alice Kendo",
    emergency_contact_name: str = "Bob Kendo",
    emergency_contact_phone: str = "07700900000",
    federation_number: str = "FED-001",
) -> dict:
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


# ── AC1 — Personal Details section visible ───────────────────────────────────


def test_settings_shows_personal_details_section(page: Page) -> None:
    email = f"ac1_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC2 — Summary shows current Member record values ─────────────────────────


def test_settings_summary_shows_member_record_values(page: Page) -> None:
    email = f"ac2_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Prepop Tester")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Values are visible in the read-only summary
    expect(page.get_by_text("Prepop Tester")).to_be_visible()
    expect(page.get_by_text("Bob Kendo")).to_be_visible()
    expect(page.get_by_text("FED-001")).to_be_visible()


# ── AC3 — Saving returns to summary with updated values ──────────────────────


def test_settings_save_returns_to_summary_with_updated_values(page: Page) -> None:
    email = f"ac3_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Original Name")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Full name").fill("Updated Name")
    page.get_by_role("button", name="Save changes").click()

    # Returns to view mode showing the new value
    expect(page.get_by_text("Updated Name")).to_be_visible()
    expect(page.get_by_label("Full name")).not_to_be_visible()


# ── AC4 — Backend error surfaces as inline error message ─────────────────────


def test_settings_backend_error_shows_inline_message(page: Page) -> None:
    email = f"ac4_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Error Tester")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()

    def handle_route(route: Route) -> None:
        route.fulfill(
            status=500,
            content_type="application/json",
            body='{"detail": "Internal server error"}',
        )

    page.route("**/api/users/me/member", handle_route, times=1)

    page.get_by_label("Full name").fill("Will Fail")
    page.get_by_role("button", name="Save changes").click()

    # Error message appears; stays in edit mode
    expect(page.get_by_role("alert")).to_be_visible()
    expect(page.get_by_label("Full name")).to_be_visible()


# ── AC5 — No Member record: "Set up profile", save creates the record ─────────


def test_settings_set_up_profile_when_no_member_record(page: Page) -> None:
    email = f"ac5_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # No member record → "Set up profile" button
    expect(page.get_by_role("button", name="Set up profile")).to_be_visible()

    page.get_by_role("button", name="Set up profile").click()

    # Form shown with empty fields
    expect(page.get_by_label("Full name")).to_have_value("")

    page.get_by_label("Full name").fill("New Member")
    page.get_by_role("button", name="Save changes").click()

    # Returns to summary showing the new name
    expect(page.get_by_text("New Member")).to_be_visible()
    expect(page.get_by_label("Full name")).not_to_be_visible()


# ── AC6 — /profile redirects to /settings ────────────────────────────────────


def test_profile_redirects_to_settings(page: Page) -> None:
    email = f"ac6_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/profile")

    expect(page).to_have_url(f"{BASE_URL}/settings")
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC7 — Layout usable on mobile ────────────────────────────────────────────


def test_settings_layout_usable_on_mobile(page: Page) -> None:
    page.set_viewport_size({"width": 375, "height": 667})
    email = f"ac7m_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_text("Personal Details")).to_be_visible()
    expect(page.get_by_role("button", name="Edit")).to_be_visible()


# ── AC7 — Layout usable on desktop ───────────────────────────────────────────


def test_settings_layout_usable_on_desktop(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    email = f"ac7d_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_text("Personal Details")).to_be_visible()
    expect(page.get_by_role("button", name="Edit")).to_be_visible()


# ── AC8 — Edit name, save, reload: updated name persists ─────────────────────


def test_settings_edit_name_persists_after_reload(page: Page) -> None:
    email = f"ac8_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Before Reload")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Full name").fill("After Reload")
    page.get_by_role("button", name="Save changes").click()

    page.reload()

    # After reload, summary shows the updated name
    expect(page.get_by_text("After Reload")).to_be_visible()


# ── AC9 — Default view is read-only summary (no form) ────────────────────────


def test_settings_shows_read_only_summary_by_default(page: Page) -> None:
    email = f"ac9_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Summary User")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Summary visible
    expect(page.get_by_text("Summary User")).to_be_visible()
    expect(page.get_by_role("button", name="Edit")).to_be_visible()
    # Form inputs NOT visible
    expect(page.get_by_label("Full name")).not_to_be_visible()


# ── AC10 — Edit button shows the form ────────────────────────────────────────


def test_settings_edit_button_shows_form(page: Page) -> None:
    email = f"ac10_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Edit Button User")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()

    # Form inputs now visible, pre-filled
    expect(page.get_by_label("Full name")).to_be_visible()
    expect(page.get_by_label("Full name")).to_have_value("Edit Button User")
    expect(page.get_by_role("button", name="Cancel")).to_be_visible()
    expect(page.get_by_role("button", name="Save changes")).to_be_visible()


# ── AC11 — Cancel returns to summary without saving ──────────────────────────


def test_settings_cancel_returns_to_summary_without_saving(page: Page) -> None:
    email = f"ac11_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, full_name="Cancel Test User")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Full name").fill("Should Not Save")
    page.get_by_role("button", name="Cancel").click()

    # Returns to summary — original value shown, form gone
    expect(page.get_by_text("Cancel Test User")).to_be_visible()
    expect(page.get_by_label("Full name")).not_to_be_visible()
    expect(page.get_by_text("Should Not Save")).not_to_be_visible()


# ── AC12 — Save returns to summary with updated values ───────────────────────
# (covered by AC3 above — kept as alias for traceability)


@pytest.mark.skip(reason="Covered by test_settings_save_returns_to_summary_with_updated_values")
def test_settings_save_returns_to_summary_alias() -> None:
    pass
