"""
Playwright browser tests for issue #10 — Admin attendance management.

ACs covered:
  AC1 — Admin can mark any member as attended for a session
  AC2 — Admin can remove a member's attendance record for a session
  AC3 — Admin can add a visitor record to a session with a name only
  AC4 — Visitor records appear in the session attendance list alongside member check-ins
  AC5 — GET /members/{id}/attendance returns full history (admin any; member own only)
  AC6 — Member cannot access another member's attendance history (403)

Setup strategy
--------------
Tests use the live backend (SQLite dev DB) and the Vite dev server.  Each test
creates its own data via the backend API and drives the UI with Playwright.

The admin account (admin@test.com / testpass123) is assumed to already exist as
the first registered user (role=admin).

Session isolation: each test creates sessions on a unique future date
(different per test via time offsets) so the sessions page only shows
that test's session when filtered — but since we cannot filter in the UI,
we instead scope the Playwright interaction to the *last* card in the list
(the most recently scheduled session appears last chronologically).

AC5b (member viewing own attendance history) and AC6 (member blocked from
another member's history): the /members/:id route is admin-only in the React
router, so members are redirected to /.  These ACs are enforced at the API
level; the browser tests verify the API response directly via page.evaluate
after logging in via the UI to obtain a session cookie.
"""

from __future__ import annotations

import uuid

import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "testpass123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_login(email: str, password: str) -> dict:
    """Log in via the API and return the cookie dict."""
    r = requests.post(
        f"{API_URL}/auth/login/password",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return r.cookies.get_dict()


def _api_register(email: str, password: str) -> dict:
    """Register a new user and return the UserClaims dict."""
    r = requests.post(
        f"{API_URL}/auth/register/password",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return r.json()


def _api_create_member(admin_cookies: dict, email: str, full_name: str) -> dict:
    """Create a member record via the admin API (no user_id link)."""
    r = requests.post(
        f"{API_URL}/members",
        cookies=admin_cookies,
        json={
            "email": email,
            "full_name": full_name,
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
            "parental_consent_obtained": False,
        },
    )
    r.raise_for_status()
    return r.json()


def _api_self_onboard_member(email: str, password: str, full_name: str) -> dict:
    """Register a user and create+link their own member record via PUT /users/me/member.

    Returns the member record dict.  The member record's user_id will equal
    the user's sub, so GET /members/{member_id}/attendance will allow self-access.
    """
    r = requests.post(
        f"{API_URL}/auth/login/password",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    member_cookies = r.cookies.get_dict()

    r = requests.put(
        f"{API_URL}/users/me/member",
        cookies=member_cookies,
        json={"full_name": full_name},
    )
    r.raise_for_status()
    return r.json()


def _api_get_session_type_id(admin_cookies: dict) -> str:
    """Return the first session-type ID (created by app lifespan)."""
    r = requests.get(f"{API_URL}/session-types", cookies=admin_cookies)
    r.raise_for_status()
    return r.json()[0]["id"]


def _api_create_session(admin_cookies: dict, date: str = "2026-05-01") -> dict:
    """Create an ad-hoc session instance on the given date."""
    type_id = _api_get_session_type_id(admin_cookies)
    r = requests.post(
        f"{API_URL}/sessions",
        cookies=admin_cookies,
        json={
            "session_type_id": type_id,
            "date": date,
            "start_time": "18:00",
            "duration_minutes": 90,
        },
    )
    r.raise_for_status()
    return r.json()


def _api_mark_attended(admin_cookies: dict, session_id: str, member_id: str) -> dict:
    r = requests.post(
        f"{API_URL}/sessions/{session_id}/attendance",
        cookies=admin_cookies,
        json={"member_id": member_id},
    )
    r.raise_for_status()
    return r.json()


def _login_ui(page: Page, email: str, password: str) -> None:
    """Log in via the UI password form and wait for redirect to /."""
    page.goto(f"{BASE_URL}/login")
    page.get_by_role("button", name="Use email and password instead").click()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE_URL}/")


def _open_last_attendance_panel(page: Page) -> None:
    """
    Open the Attendance panel on the last session card in the list.
    Each test creates sessions on unique future dates so the newest session
    (chronologically last) is the one we want.
    """
    # All Attendance toggle buttons — pick the last one (newest session)
    toggles = page.get_by_role("button", name="Attendance")
    count = toggles.count()
    toggles.nth(count - 1).click()


# ---------------------------------------------------------------------------
# AC1 — Admin marks member attended
# ---------------------------------------------------------------------------


def test_admin_can_mark_member_attended(page: Page) -> None:
    # Unique date so this session sorts last
    test_date = "2026-06-01"
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    _api_create_session(admin_cookies, date=test_date)

    suffix = uuid.uuid4().hex[:8]
    email = f"member_ac1_{suffix}@test.com"
    _api_register(email, "testpass123")
    member = _api_create_member(admin_cookies, email, f"Member AC1 {suffix}")
    member_id = member["id"]

    _login_ui(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.goto(f"{BASE_URL}/sessions")

    _open_last_attendance_panel(page)

    # Fill in the member ID and submit
    page.get_by_label("Member ID to mark attended").fill(member_id)
    page.get_by_label("Mark member attended").click()

    # The attendance list should now show the member's truncated ID
    truncated = member_id[:8] + "\u2026"
    expect(page.get_by_label("Attendance list").last).to_contain_text(truncated)


# ---------------------------------------------------------------------------
# AC2 — Admin removes member attendance
# ---------------------------------------------------------------------------


def test_admin_can_remove_member_attendance(page: Page) -> None:
    test_date = "2026-06-02"
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    session = _api_create_session(admin_cookies, date=test_date)
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    email = f"member_ac2_{suffix}@test.com"
    _api_register(email, "testpass123")
    member = _api_create_member(admin_cookies, email, f"Member AC2 {suffix}")
    member_id = member["id"]

    # Mark the member as attended first (via API)
    _api_mark_attended(admin_cookies, session_id, member_id)

    _login_ui(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.goto(f"{BASE_URL}/sessions")

    _open_last_attendance_panel(page)

    # The member should be listed
    truncated = member_id[:8] + "\u2026"
    last_list = page.get_by_label("Attendance list").last
    expect(last_list).to_contain_text(truncated)

    # Click the Remove button for that member
    remove_btn = page.get_by_label(f"Remove attendance for {member_id[:8]}")
    remove_btn.click()

    # The member should no longer appear in the list
    # After removal the list may be empty — just confirm the truncated ID is gone
    # (the "No attendees yet" message appears when the list is empty)
    expect(page.get_by_text("No attendees yet").last).to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — Admin adds a visitor record
# ---------------------------------------------------------------------------


def test_admin_can_add_visitor_to_session(page: Page) -> None:
    test_date = "2026-06-03"
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    _api_create_session(admin_cookies, date=test_date)

    visitor_name = f"John Visitor {uuid.uuid4().hex[:6]}"

    _login_ui(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.goto(f"{BASE_URL}/sessions")

    _open_last_attendance_panel(page)

    # Fill visitor name and submit
    page.get_by_label("Visitor name").fill(visitor_name)
    page.get_by_label("Add visitor").click()

    # Visitor name should appear in the attendance list
    expect(page.get_by_label("Attendance list").last).to_contain_text(visitor_name)


# ---------------------------------------------------------------------------
# AC4 — Session attendance list shows members and visitors together
# ---------------------------------------------------------------------------


def test_session_attendance_list_shows_visitors_alongside_members(page: Page) -> None:
    test_date = "2026-06-04"
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    session = _api_create_session(admin_cookies, date=test_date)
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    email = f"member_ac4_{suffix}@test.com"
    _api_register(email, "testpass123")
    member = _api_create_member(admin_cookies, email, f"Member AC4 {suffix}")
    member_id = member["id"]

    # Mark member attended and add a visitor via API
    _api_mark_attended(admin_cookies, session_id, member_id)
    visitor_name = f"Visitor AC4 {uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{API_URL}/sessions/{session_id}/visitors",
        cookies=admin_cookies,
        json={"visitor_name": visitor_name},
    )
    r.raise_for_status()

    _login_ui(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.goto(f"{BASE_URL}/sessions")

    _open_last_attendance_panel(page)

    # Both member (truncated ID) and visitor should appear together
    truncated = member_id[:8] + "\u2026"
    last_list = page.get_by_label("Attendance list").last
    expect(last_list).to_contain_text(truncated)
    expect(last_list).to_contain_text(visitor_name)
    # Visitor badge
    expect(last_list).to_contain_text("Visitor")


# ---------------------------------------------------------------------------
# AC5a — Admin can view any member's attendance history (UI)
# ---------------------------------------------------------------------------


def test_admin_can_view_any_member_attendance_history(page: Page) -> None:
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    session = _api_create_session(admin_cookies, date="2026-06-05")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    email = f"member_ac5a_{suffix}@test.com"
    _api_register(email, "testpass123")
    member = _api_create_member(admin_cookies, email, f"Member AC5a {suffix}")
    member_id = member["id"]

    # Mark member attended so there's history to show
    _api_mark_attended(admin_cookies, session_id, member_id)

    _login_ui(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.goto(f"{BASE_URL}/members/{member_id}")

    # The Attendance History card title (a <div data-slot="card-title">)
    expect(page.locator('[data-slot="card-title"]', has_text="Attendance History")).to_be_visible()

    # Expand attendance history — button text is "Show attendance (1 sessions)"
    page.get_by_role("button", name="Show attendance").click()

    # The attendance history list (#attendance-history-list) should appear
    expect(page.locator("#attendance-history-list")).to_be_visible()


# ---------------------------------------------------------------------------
# AC5b — Member can view own attendance history via API
# (The /members/:id UI route is admin-only; AC5b is enforced at the API layer.
#  We verify the API returns 200 for self after logging in via the UI.)
# ---------------------------------------------------------------------------


def test_member_can_view_own_attendance_history(page: Page) -> None:
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    session = _api_create_session(admin_cookies, date="2026-06-06")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    email = f"member_ac5b_{suffix}@test.com"
    _api_register(email, "testpass123")

    # Self-onboard: PUT /users/me/member creates a member record with user_id linked,
    # so the router's get_by_user_id lookup will resolve correctly for self-access.
    member = _api_self_onboard_member(email, "testpass123", f"Member AC5b {suffix}")
    member_id = member["id"]

    # Mark member attended so history exists
    _api_mark_attended(admin_cookies, session_id, member_id)

    # Log in as the member via the UI (establishes the session cookie in the browser)
    _login_ui(page, email, "testpass123")

    # Call the API from the browser (shares the httpOnly cookie set by the UI login)
    result = page.evaluate(
        """async (memberId) => {
            const res = await fetch(`/api/members/${memberId}/attendance`, {
                credentials: 'include'
            });
            return { status: res.status, count: (await res.json()).length };
        }""",
        member_id,
    )

    assert result["status"] == 200, f"Expected 200, got {result['status']}"
    assert result["count"] >= 1, f"Expected at least 1 record, got {result['count']}"


# ---------------------------------------------------------------------------
# AC6 — Member cannot view another member's attendance history
# ---------------------------------------------------------------------------


def test_member_cannot_view_other_member_attendance_history(page: Page) -> None:
    admin_cookies = _api_login(ADMIN_EMAIL, ADMIN_PASSWORD)
    session = _api_create_session(admin_cookies, date="2026-06-07")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]

    # Target member (has attendance)
    target_email = f"target_ac6_{suffix}@test.com"
    _api_register(target_email, "testpass123")
    target_member = _api_create_member(admin_cookies, target_email, f"Target AC6 {suffix}")
    target_member_id = target_member["id"]
    _api_mark_attended(admin_cookies, session_id, target_member_id)

    # Viewer member (tries to access target's history)
    viewer_email = f"viewer_ac6_{suffix}@test.com"
    _api_register(viewer_email, "testpass123")

    # Log in as the viewer via the UI
    _login_ui(page, viewer_email, "testpass123")

    # Verify the API returns 403 when the member tries to access another member's history
    result = page.evaluate(
        """async (targetMemberId) => {
            const res = await fetch(`/api/members/${targetMemberId}/attendance`, {
                credentials: 'include'
            });
            return { status: res.status };
        }""",
        target_member_id,
    )

    assert result["status"] == 403, f"Expected 403, got {result['status']}"
