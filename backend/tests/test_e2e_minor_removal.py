"""
Playwright browser tests for issue #262 — remove derived `is_minor` flag and
all minor-related UI.

AC3: No "Minor" badge (or parental-consent affordance) renders anywhere:
  1. Members list page
  2. Member detail page
  3. Settings page

Each test seeds a member whose date of birth would previously have made
`is_minor` True (i.e. under 18 today), so the assertion of absence is
anchored to a page that actually loaded and rendered that member — not a
blank/error page where "Minor" would trivially be absent.
"""

from __future__ import annotations

import uuid
from datetime import date

import requests
from playwright.sync_api import Page, expect

from tests.e2e_support import complete_onboarding, make_token, set_cookie

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000/api"

# A dob that makes the person ~10 years old today — well under 18, so prior to
# this change the backend would have computed is_minor=True and the frontend
# would have rendered the "Minor" badge. Pinned to Jan 1 rather than derived via
# date.replace(year=...), which raises ValueError when today is Feb 29.
_MINOR_DOB = f"{date.today().year - 10}-01-01"

_CONSENT_ARIA_SELECTOR = '[aria-label*="parental consent" i]'


def _assert_no_minor_affordance(page: Page) -> None:
    """Assert neither a literal 'Minor' badge nor a parental-consent
    aria-label is present anywhere on the currently loaded page."""
    expect(page.get_by_text("Minor", exact=True)).to_have_count(0)
    expect(page.locator(_CONSENT_ARIA_SELECTOR)).to_have_count(0)


def _create_member_via_api(
    admin_token: str, first_name: str, surname: str, dob: str
) -> dict:
    resp = requests.post(
        f"{API_BASE}/members",
        cookies={"access_token": admin_token},
        json={
            "email": f"minor-{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": first_name,
            "surname": surname,
            "dob": dob,
            "join_date": "2024-01-01",
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
        },
    )
    resp.raise_for_status()
    return resp.json()


def _member_display_name(member: dict) -> str:
    return f"{member['first_name']} {member['surname']}"


# ---------------------------------------------------------------------------
# AC3.1 — Members list page
# ---------------------------------------------------------------------------


def test_no_minor_badge_on_members_list(page: Page) -> None:
    admin_token = make_token("admin")
    complete_onboarding(admin_token)
    member = _create_member_via_api(
        admin_token, "Minorly", f"Childtest{uuid.uuid4().hex[:6]}", _MINOR_DOB
    )

    set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members")
    page.wait_for_load_state("networkidle")

    # The full suite seeds far more members than one page shows, so filter down
    # to this member's unique surname rather than hoping the row is on page 1.
    page.get_by_label("Search members").fill(member["surname"])

    # Anchor: the minor member's row actually rendered — guards against a
    # vacuous pass on a blank/error page. Scoped by role because the page keeps
    # both the desktop table row (role=row) and the mobile card (role=button) in
    # the DOM, hiding one by CSS; a bare text match hits both.
    expect(
        page.get_by_role("row", name=f"View {_member_display_name(member)}")
    ).to_be_visible(timeout=8000)

    _assert_no_minor_affordance(page)


# ---------------------------------------------------------------------------
# AC3.2 — Member detail page
# ---------------------------------------------------------------------------


def test_no_minor_badge_on_member_detail(page: Page) -> None:
    admin_token = make_token("admin")
    complete_onboarding(admin_token)
    member = _create_member_via_api(
        admin_token, "Detailminor", f"Childtest{uuid.uuid4().hex[:6]}", _MINOR_DOB
    )

    set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member['id']}")
    page.wait_for_load_state("networkidle")

    # Anchor: the detail page loaded and rendered this member's heading.
    expect(
        page.get_by_role("heading", name=_member_display_name(member))
    ).to_be_visible(timeout=8000)

    _assert_no_minor_affordance(page)


# ---------------------------------------------------------------------------
# AC3.3 — Settings page (self profile)
# ---------------------------------------------------------------------------


def test_no_minor_badge_on_settings_page(page: Page) -> None:
    member_token = make_token("member")
    first_name = "Selfminor"
    surname = f"Childtest{uuid.uuid4().hex[:6]}"
    complete_onboarding(
        member_token, first_name=first_name, surname=surname, dob=_MINOR_DOB
    )

    set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/settings")
    page.wait_for_load_state("networkidle")

    # Anchor: the profile summary actually rendered this member's own name.
    expect(page.get_by_text(first_name, exact=True)).to_be_visible(timeout=8000)

    _assert_no_minor_affordance(page)
