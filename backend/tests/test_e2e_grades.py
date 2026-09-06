"""
Playwright E2E tests for issue #8 — Grade promotion UI.

One test per acceptance criterion that has a frontend component.
Auth pattern: synthetic JWT tokens injected as cookies (same as test_e2e_attendance_admin.py).
"""

import os
import uuid

import requests
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000/api"


def _make_token(role: str, sub: str | None = None) -> str:
    claims = UserClaims(
        sub=sub or str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _cookie_dict(token: str) -> dict:
    return {"access_token": token}


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _get_session_type_id(admin_token: str) -> str:
    r = requests.get(f"{API_BASE}/session-types", cookies=_cookie_dict(admin_token))
    r.raise_for_status()
    return r.json()[0]["id"]


def _set_grade_via_api(admin_token: str, member_id: str, grade: str) -> None:
    r = requests.post(
        f"{API_BASE}/members/{member_id}/grades",
        cookies=_cookie_dict(admin_token),
        json={"grade": grade},
    )
    r.raise_for_status()


def _create_member_via_api(
    admin_token: str, full_name: str, email: str | None = None
) -> str:
    parts = full_name.split(" ", 1)
    r = requests.post(
        f"{API_BASE}/members",
        cookies=_cookie_dict(admin_token),
        json={
            "email": email or f"member-{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": parts[0],
            "surname": parts[1] if len(parts) > 1 else parts[0],
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
        },
    )
    r.raise_for_status()
    return r.json()["id"]


# CardTitle in shadcn renders as a div[data-slot="card-title"], not a semantic
# heading element, so we locate it by text content within that slot.
_GRADE_CARD_TITLE = '[data-slot="card-title"]:has-text("Grade")'


# ---------------------------------------------------------------------------
# AC1/AC5 — Grade card shows member's current grade
# ---------------------------------------------------------------------------


def test_grade_shown_on_member_detail(page: Page) -> None:
    """AC1/AC5: Member detail page shows the member's current grade."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "Grade Display Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_text("Mukyū")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC2/AC7 — Edit grade button visible for admin (replaces old Promote button)
# ---------------------------------------------------------------------------


def test_promote_button_visible_for_admin(page: Page) -> None:
    """AC2/AC7: Edit grade button is visible on the member detail page for admins."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "Promote Button Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_role("button", name="Edit member grade")).to_be_visible(
        timeout=8000
    )


# ---------------------------------------------------------------------------
# AC4/AC6 — Grade history toggle works
# ---------------------------------------------------------------------------


def test_grade_history_visible_to_member(page: Page) -> None:
    """AC4/AC6: Grade history toggle appears once a grade exists and expands correctly."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "History Toggle Member")
    _set_grade_via_api(admin_token, member_id, "ROKKYUU")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    toggle = page.locator("button", has_text="grade history")
    expect(toggle).to_be_visible(timeout=8000)

    toggle.click()
    expect(page.locator("#grade-history-list")).to_be_visible(timeout=5000)

    toggle.click()
    expect(page.locator("#grade-history-list")).not_to_be_visible(timeout=5000)


# ===========================================================================
# Issue #144 — New grade UI tests
# ===========================================================================

# ---------------------------------------------------------------------------
# AC7 — Frontend promote button is gone; admin edit button opens set-grade dialog
# ---------------------------------------------------------------------------


def test_promote_button_removed_edit_button_present(page: Page) -> None:
    """AC7: The old Promote button is gone; an Edit grade button opens the grade dialog."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "AC7 Grade Edit Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)

    # Old "Promote member" button must NOT be visible
    expect(page.get_by_role("button", name="Promote member")).not_to_be_visible()

    # New "Edit grade" button must be visible
    expect(page.get_by_role("button", name="Edit member grade")).to_be_visible(
        timeout=8000
    )


# ---------------------------------------------------------------------------
# AC8 — Dialog grade dropdown shows 14 options (MUKYUU excluded)
# ---------------------------------------------------------------------------


def test_grade_dialog_dropdown_has_14_options_mukyuu_excluded(page: Page) -> None:
    """AC8: The set-grade dialog dropdown must list exactly 14 grades (MUKYUU excluded)."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "AC8 Grade Dropdown Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)

    # Open the edit grade dialog
    page.get_by_role("button", name="Edit member grade").click()

    # Open the grade Select dropdown
    page.get_by_role("combobox", name="Select grade").click()

    # Count the visible SelectItem options
    options = page.locator('[role="option"]')
    options.first.wait_for(timeout=5000)
    count = options.count()
    assert count == 14, f"Expected 14 grade options, got {count}"

    # Mukyū must NOT appear in the dropdown
    mukyuu_option = page.locator('[role="option"]', has_text="Mukyū")
    expect(mukyuu_option).not_to_be_visible()


# ---------------------------------------------------------------------------
# AC9 — Successful submission updates the grade card without page reload
# ---------------------------------------------------------------------------


def test_grade_card_updates_without_page_reload_after_set_grade(page: Page) -> None:
    """AC9: After submitting the set-grade dialog the grade card reflects the new grade
    without a full page reload."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "AC9 Grade Update Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)

    # Plant a sentinel on the window to detect page reloads
    page.evaluate("window.__noReload = true")

    # Open the edit grade dialog
    page.get_by_role("button", name="Edit member grade").click()

    # Select "Shodan (1-dan)" from the dropdown
    page.get_by_role("combobox", name="Select grade").click()
    page.get_by_role("option", name="Shodan (1-dan)").click()

    # Submit
    page.get_by_role("button", name="Save").click()

    # Wait for the dialog to close
    expect(page.get_by_role("dialog")).not_to_be_visible(timeout=8000)

    # Confirm the sentinel is still set (no page reload occurred)
    sentinel = page.evaluate("window.__noReload")
    assert sentinel is True, "Page was reloaded — grade card must update without reload"

    # Grade card <p> shows the new grade (scoped to <p> to avoid hidden Select trigger div)
    expect(page.locator("p", has_text="Shodan (1-dan)").first).to_be_visible(
        timeout=8000
    )
