"""
Playwright browser tests for issue #10 — Admin attendance management.

ACs covered:
  AC1 — Admin can mark any member as attended for a session
  AC2 — Admin can remove a member's attendance record for a session
  AC3 — Admin can add a visitor record to a session with a name only
  AC4 — Visitor records appear in the session attendance list alongside member check-ins
  AC5 — GET /members/{id}/attendance returns full history (admin any; member own only)
  AC6 — Member cannot access another member's attendance history (403)

Auth pattern: synthetic JWT tokens injected as cookies (same as test_e2e_attendance.py).
No real user registration required. members.user_id has no FK constraint so synthetic
UUIDs from JWT claims can link member records without a real users row.
"""

from __future__ import annotations

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

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(role: str, sub: str | None = None) -> str:
    claims = UserClaims(
        sub=sub or str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _cookie_dict(token: str) -> dict:
    return {"access_token": token}


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _api_get_session_type_id(admin_token: str) -> str:
    r = requests.get(f"{API_URL}/session-types", cookies=_cookie_dict(admin_token))
    r.raise_for_status()
    return r.json()[0]["id"]


def _api_create_session(admin_token: str, date: str = "2299-06-01") -> dict:
    type_id = _api_get_session_type_id(admin_token)
    r = requests.post(
        f"{API_URL}/sessions",
        cookies=_cookie_dict(admin_token),
        json={
            "session_type_id": type_id,
            "date": date,
            "start_time": "18:00",
            "duration_minutes": 90,
        },
    )
    r.raise_for_status()
    return r.json()


def _api_create_member(admin_token: str, full_name: str) -> dict:
    r = requests.post(
        f"{API_URL}/members",
        cookies=_cookie_dict(admin_token),
        json={
            "email": f"member-{uuid.uuid4().hex[:8]}@dojo.test",
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


def _api_create_member_with_user_id(member_sub: str, full_name: str) -> dict:
    """Create member via PUT /users/me/member with member's own JWT.

    members.user_id has no FK constraint so member_sub need not be in users table.
    The self-access check in GET /members/{id}/attendance uses
    get_by_user_id(claims.sub) which will match this member's user_id.
    """
    member_token = _make_token("member", sub=member_sub)
    r = requests.put(
        f"{API_URL}/users/me/member",
        cookies=_cookie_dict(member_token),
        json={"full_name": full_name},
    )
    r.raise_for_status()
    return r.json()


def _api_mark_attended(admin_token: str, session_id: str, member_id: str) -> dict:
    r = requests.post(
        f"{API_URL}/sessions/{session_id}/attendance",
        cookies=_cookie_dict(admin_token),
        json={"member_id": member_id},
    )
    r.raise_for_status()
    return r.json()


def _open_last_attendance_panel(page: Page) -> None:
    toggles = page.get_by_role("button", name="Attendance")
    count = toggles.count()
    toggles.nth(count - 1).click()


def _open_session_panel(page: Page, session_id: str):
    """Open the attendance panel for a specific session and return its locator."""
    panel = page.locator(f'[data-session-id="{session_id}"]')
    panel.get_by_role("button", name="Attendance").click()
    return panel


# ---------------------------------------------------------------------------
# AC1 — Admin marks member attended
# ---------------------------------------------------------------------------


def test_admin_can_mark_member_attended(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-01")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    full_name = f"Member AC1 {suffix}"
    member = _api_create_member(admin_token, full_name)
    member_id = member["id"]

    page.set_viewport_size({"width": 375, "height": 667})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    panel = _open_session_panel(page, session_id)

    panel.get_by_label("Member ID to mark attended").fill(member_id)
    panel.get_by_label("Mark member attended").click()

    # UI shows display_name (member's full_name) after successful mark
    expect(panel.get_by_label("Attendance list")).to_contain_text(full_name)


# ---------------------------------------------------------------------------
# AC2 — Admin removes member attendance
# ---------------------------------------------------------------------------


def test_admin_can_remove_member_attendance(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-02")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    full_name = f"Member AC2 {suffix}"
    member = _api_create_member(admin_token, full_name)
    member_id = member["id"]

    _api_mark_attended(admin_token, session_id, member_id)

    page.set_viewport_size({"width": 375, "height": 667})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    panel = _open_session_panel(page, session_id)

    expect(panel.get_by_label("Attendance list")).to_contain_text(full_name)

    # aria-label uses display_name when available
    panel.get_by_label(f"Remove attendance for {full_name}").click()

    expect(panel.get_by_text("No attendees yet")).to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — Admin adds a visitor record
# ---------------------------------------------------------------------------


def test_admin_can_add_visitor_to_session(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-03")
    session_id = session["id"]

    visitor_name = f"John Visitor {uuid.uuid4().hex[:6]}"

    page.set_viewport_size({"width": 375, "height": 667})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    panel = _open_session_panel(page, session_id)

    panel.get_by_label("Visitor name").fill(visitor_name)
    panel.get_by_label("Add visitor").click()

    expect(panel.get_by_label("Attendance list")).to_contain_text(visitor_name)


# ---------------------------------------------------------------------------
# AC4 — Session attendance list shows members and visitors together
# ---------------------------------------------------------------------------


def test_session_attendance_list_shows_visitors_alongside_members(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-04")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    full_name = f"Member AC4 {suffix}"
    member = _api_create_member(admin_token, full_name)
    member_id = member["id"]

    _api_mark_attended(admin_token, session_id, member_id)
    visitor_name = f"Visitor AC4 {uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{API_URL}/sessions/{session_id}/visitors",
        cookies=_cookie_dict(admin_token),
        json={"visitor_name": visitor_name},
    )
    r.raise_for_status()

    page.set_viewport_size({"width": 375, "height": 667})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    panel = _open_session_panel(page, session_id)

    expect(panel.get_by_label("Attendance list")).to_contain_text(full_name)
    expect(panel.get_by_label("Attendance list")).to_contain_text(visitor_name)
    expect(panel.get_by_label("Attendance list")).to_contain_text("Visitor")


# ---------------------------------------------------------------------------
# AC5a — Admin can view any member's attendance history (UI)
# ---------------------------------------------------------------------------


def test_admin_can_view_any_member_attendance_history(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-05")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    member = _api_create_member(admin_token, f"Member AC5a {suffix}")
    member_id = member["id"]

    _api_mark_attended(admin_token, session_id, member_id)

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(
        page.locator('[data-slot="card-title"]', has_text="Attendance History")
    ).to_be_visible()

    page.get_by_role("button", name="Show attendance").click()

    expect(page.locator("#attendance-history-list")).to_be_visible()


# ---------------------------------------------------------------------------
# AC5b — Member can view own attendance history via API
# ---------------------------------------------------------------------------


def test_member_can_view_own_attendance_history(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-06")
    session_id = session["id"]

    # Create member with user_id = member_sub (FK removed, no real user needed)
    member_sub = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    member = _api_create_member_with_user_id(member_sub, f"Member AC5b {suffix}")
    member_id = member["id"]

    _api_mark_attended(admin_token, session_id, member_id)

    # Inject member JWT — get_by_user_id(member_sub) finds this member → 200
    member_token = _make_token("member", sub=member_sub)
    _inject_cookie(page, member_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

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
    admin_token = _make_token("admin")
    session = _api_create_session(admin_token, date="2299-06-07")
    session_id = session["id"]

    suffix = uuid.uuid4().hex[:8]
    target_member = _api_create_member(admin_token, f"Target AC6 {suffix}")
    target_member_id = target_member["id"]
    _api_mark_attended(admin_token, session_id, target_member_id)

    # Viewer has JWT but no linked member record → get_by_user_id returns None → 403
    viewer_token = _make_token("member")
    _inject_cookie(page, viewer_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

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
