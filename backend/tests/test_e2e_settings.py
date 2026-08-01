"""
Playwright browser tests for issue #27/#28 — Settings page: Personal Details.
Updated for issue #158/#159 (first_name/surname/display_name/dob fields).

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


def _register_api(email: str) -> str:
    resp = requests.post(
        f"{API_URL}/auth/login/test", json={"email": email, "role": "admin"}
    )
    resp.raise_for_status()
    return resp.json()["sub"]


def _login_api(email: str) -> str:
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


def _create_member_record(
    token: str,
    first_name: str = "Alice",
    surname: str = "Kendo",
    emergency_contact_name: str = "Bob Kendo",
    emergency_contact_phone: str = "07700900000",
) -> dict:
    resp = requests.put(
        f"{API_URL}/users/me/member",
        json={
            "first_name": first_name,
            "surname": surname,
            "dob": "1990-05-15",
            "emergency_contact_name": emergency_contact_name,
            "emergency_contact_phone": emergency_contact_phone,
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
    # A profile is required to reach /settings; without one RequireProfile
    # redirects to /onboarding (#221).
    _create_member_record(token)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC2 — Summary shows current Member record values ─────────────────────────


def test_settings_summary_shows_member_record_values(page: Page) -> None:
    email = f"ac2_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Prepop", surname="Tester")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Values are visible in the read-only summary. Use exact matches: the name
    # also appears combined in the summary header ("Prepop Tester"), so a
    # substring match is ambiguous (strict-mode violation).
    expect(page.get_by_text("Prepop", exact=True)).to_be_visible()
    expect(page.get_by_text("Tester", exact=True)).to_be_visible()
    expect(page.get_by_text("Bob Kendo", exact=True)).to_be_visible()


# ── AC3 — Saving returns to summary with updated values ──────────────────────


def test_settings_save_returns_to_summary_with_updated_values(page: Page) -> None:
    email = f"ac3_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Original", surname="Name")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("First name").fill("Updated")
    page.get_by_role("button", name="Save changes").click()

    # Returns to view mode showing the new value (exact: avoids matching the
    # combined "Updated Name" summary header as well as the field value).
    expect(page.get_by_text("Updated", exact=True)).to_be_visible()
    expect(page.get_by_label("First name")).not_to_be_visible()


# ── AC4 — Backend error surfaces as inline error message ─────────────────────


def test_settings_backend_error_shows_inline_message(page: Page) -> None:
    email = f"ac4_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Error", surname="Tester")

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

    page.get_by_label("First name").fill("Will Fail")
    page.get_by_role("button", name="Save changes").click()

    # Error message appears; stays in edit mode
    expect(page.get_by_role("alert")).to_be_visible()
    expect(page.get_by_label("First name")).to_be_visible()


# ── AC5 — No Member record: profile setup happens via /onboarding ─────────────


def test_settings_set_up_profile_when_no_member_record(page: Page) -> None:
    # The old in-settings "Set up profile" flow was replaced by the dedicated
    # /onboarding page (#160/#221): a user with no member record who visits a
    # profile-gated route is redirected there to complete their profile.
    email = f"ac5_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # No member record → redirected to onboarding
    expect(page).to_have_url(f"{BASE_URL}/onboarding")
    expect(page.get_by_role("heading", name="Complete your profile")).to_be_visible()

    page.get_by_label("First name").fill("New")
    page.get_by_label("Surname").fill("Member")
    page.get_by_label("Date of birth").fill("1990-01-01")
    page.get_by_role("button", name="Save and continue").click()

    # After completing onboarding the user lands on the dashboard with a profile.
    expect(page).to_have_url(f"{BASE_URL}/")


# ── AC6 — /profile redirects to /settings ────────────────────────────────────


def test_profile_redirects_to_settings(page: Page) -> None:
    email = f"ac6_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    # /profile redirects to /settings, but both are profile-gated: without a
    # member record RequireProfile intercepts first and sends the user to
    # /onboarding (#221). Seed a profile so the /profile→/settings hop is exercised.
    _create_member_record(token)

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
    _create_member_record(token, first_name="Before", surname="Reload")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("First name").fill("After")
    page.get_by_role("button", name="Save changes").click()

    page.reload()

    # After reload, summary shows the updated first name (exact: the header also
    # renders the combined "After Reload").
    expect(page.get_by_text("After", exact=True)).to_be_visible()


# ── AC9 — Default view is read-only summary (no form) ────────────────────────


def test_settings_shows_read_only_summary_by_default(page: Page) -> None:
    email = f"ac9_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Summary", surname="User")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # Summary visible (exact: header also renders the combined "Summary User").
    expect(page.get_by_text("Summary", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Edit")).to_be_visible()
    # Form inputs NOT visible
    expect(page.get_by_label("First name")).not_to_be_visible()


# ── AC10 — Edit button shows the form ────────────────────────────────────────


def test_settings_edit_button_shows_form(page: Page) -> None:
    email = f"ac10_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Edit", surname="User")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()

    # Form inputs now visible, pre-filled
    expect(page.get_by_label("First name")).to_be_visible()
    expect(page.get_by_label("First name")).to_have_value("Edit")
    expect(page.get_by_label("Surname")).to_have_value("User")
    expect(page.get_by_role("button", name="Cancel")).to_be_visible()
    expect(page.get_by_role("button", name="Save changes")).to_be_visible()


# ── AC11 — Cancel returns to summary without saving ──────────────────────────


def test_settings_cancel_returns_to_summary_without_saving(page: Page) -> None:
    email = f"ac11_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Cancel", surname="User")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("First name").fill("ShouldNotSave")
    page.get_by_role("button", name="Cancel").click()

    # Returns to summary — original value shown, form gone (exact: header also
    # renders the combined "Cancel User").
    expect(page.get_by_text("Cancel", exact=True)).to_be_visible()
    expect(page.get_by_label("First name")).not_to_be_visible()
    expect(page.get_by_text("ShouldNotSave")).not_to_be_visible()


# ── AC12 — Save returns to summary with updated values ───────────────────────
# (covered by AC3 above — kept as alias for traceability)


@pytest.mark.skip(
    reason="Covered by test_settings_save_returns_to_summary_with_updated_values"
)
def test_settings_save_returns_to_summary_alias() -> None:
    pass


# ── AC#159 — DOB visible in read-only summary ────────────────────────────────


def test_settings_summary_shows_dob(page: Page) -> None:
    email = f"ac159dob_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(token, first_name="Dob", surname="Tester")

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # DOB from the API ("1990-05-15") should be visible in the summary
    expect(page.get_by_text("1990-05-15")).to_be_visible()


# ── AC#159 — Display name visible as separate field ──────────────────────────


def test_settings_summary_shows_display_name_field(page: Page) -> None:
    email = f"ac159dn_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    requests.put(
        f"{API_URL}/users/me/member",
        json={
            "first_name": "Taro",
            "surname": "Yamada",
            "display_name": "Taro-san",
            # dob is required on first save, else the endpoint returns 422.
            "dob": "1990-05-15",
        },
        cookies={"access_token": token},
    ).raise_for_status()

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    # display_name appears both in the summary header and as its own field; either
    # instance proves it renders, so match the first.
    expect(page.get_by_text("Taro-san").first).to_be_visible()


# ── Issue #249 — blanking emergency contact in the UI clears it on save ──────


def test_settings_blanking_emergency_contact_clears_it(page: Page) -> None:
    """Clearing the emergency contact name field in the edit form and saving
    must remove it from the summary and keep it cleared after a reload.

    Today the backend's PUT /users/me/member strips any field whose value is
    None (issue #249), so the frontend's "blank input -> null" submission is
    silently ignored and the old value persists. This is the one criterion
    from #249 that a browser can meaningfully observe end-to-end, since the
    edit form on /settings already round-trips this field to the real API.
    """
    email = f"ac249ec_{uuid.uuid4().hex[:8]}@dojo.test"
    _register_api(email)
    token = _login_api(email)
    _create_member_record(
        token,
        first_name="Clear",
        surname="Contact",
        emergency_contact_name="Old Contact",
    )

    _inject_cookie(page, token)
    page.goto(f"{BASE_URL}/settings")

    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Emergency contact name", exact=True).fill("")
    page.get_by_role("button", name="Save changes").click()

    expect(page.get_by_text("Old Contact")).not_to_be_visible()

    page.reload()

    expect(page.get_by_text("Old Contact")).not_to_be_visible()
