"""
E2e tests for issue #9 — Attendance / Check-in.

Auth pattern: generate JWT tokens directly (same as test_e2e_sessions.py) and set
them as cookies. This avoids needing real user rows in the DB for most tests.

For check-in via token the backend stores any member_id string — no FK constraint —
so synthetic UUIDs from JWT claims work fine.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# Load the real JWT_SECRET from .env so tokens pass server-side validation.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app.auth.models import AccountClaims  # noqa: E402
from tests.e2e_support import (
    complete_onboarding,  # noqa: E402
    login_as,  # noqa: E402
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth helpers (shared with test_e2e_sessions.py pattern)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = login_as(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _set_cookie(page: Page, token: str) -> None:
    """Inject the access_token cookie into the browser context."""
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _get_or_create_session_type(page: Page, token: str) -> tuple[str, str]:
    """Return (type_id, type_name) of the first available session type."""
    resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(token),
    )
    assert resp.status == 200
    data = resp.json()
    return data[0]["id"], data[0]["name"]


def _create_session(
    page: Page,
    token: str,
    date: str,
    start_time: str = "19:00",
    title: str = "Attendance Test Session",
) -> str:
    """Create an ad-hoc session and return its id."""
    type_id, _ = _get_or_create_session_type(page, token)
    resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": title,
                "date": date,
                "segments": [
                    {
                        "start_time": start_time,
                        "duration_minutes": 60,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert resp.status == 201, f"create session failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


def _cancel_session(page: Page, token: str, session_id: str) -> None:
    resp = page.request.post(
        f"{API_URL}/sessions/{session_id}/cancel",
        headers=_api_headers(token),
    )
    assert resp.status == 200


# ---------------------------------------------------------------------------
# AC2 — Member can check in to a session via the Sessions page
# ---------------------------------------------------------------------------


def test_member_can_checkin_to_session_via_ui(page: Page) -> None:
    admin_token = _make_token("admin")
    # Start ~30 min from now so the check-in window is open (default opens 60 min
    # before start). Give the session a unique title so we can target its own card
    # rather than whatever session happens to sort first in the shared list.
    soon = datetime.now() + timedelta(minutes=30)
    title = f"Checkin UI {uuid.uuid4().hex[:8]}"
    _create_session(
        page,
        admin_token,
        soon.strftime("%Y-%m-%d"),
        start_time=soon.strftime("%H:%M"),
        title=title,
    )

    member_token = _make_token("member")
    page.set_viewport_size(
        {"width": 375, "height": 667}
    )  # mobile: shows SessionCardList
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Scope to the card for the session we created
    card = page.locator("li").filter(has_text=title)
    check_in_btn = card.get_by_role("button", name="Check In")
    expect(check_in_btn).to_be_visible(timeout=8000)

    # Click it and confirm the success state renders in that card
    check_in_btn.click()
    expect(card.get_by_text("Checked in!")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC3 — Cancelled session does not show a Check In button
# ---------------------------------------------------------------------------


def test_checkin_to_cancelled_session_shows_error(page: Page) -> None:
    """The backend filters cancelled sessions from GET /sessions, so a cancelled
    session never reaches the UI. Verify that after cancelling a session the
    Check In button count for that session is zero — i.e. the session is gone
    from the list and therefore has no actions rendered."""
    admin_token = _make_token("admin")

    # Create two sessions so we have a baseline non-cancelled session to compare
    session_id = _create_session(page, admin_token, "2099-07-22")

    # Count Check In buttons before cancellation (should be >= 1)
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")
    buttons_before = page.get_by_role("button", name="Check In").count()
    assert buttons_before >= 1, "Expected at least one Check In button before cancel"

    # Cancel the session via API
    _cancel_session(page, admin_token, session_id)

    # Verify the session is no longer returned by the API
    resp = page.request.get(
        f"{API_URL}/sessions",
        headers=_api_headers(member_token),
    )
    assert resp.status == 200
    ids = [s["id"] for s in resp.json()]
    assert session_id not in ids, "Cancelled session should not appear in API list"

    # Reload sessions page — the cancelled session should not be present
    page.reload()
    page.wait_for_load_state("networkidle")
    buttons_after = page.get_by_role("button", name="Check In").count()
    # The cancelled session contributed one Check In button; it should now be gone
    assert (
        buttons_after < buttons_before
    ), f"Expected fewer Check In buttons after cancel ({buttons_after} vs {buttons_before})"


# ---------------------------------------------------------------------------
# AC4 — Admin can share the session's check-in link from the Sessions page
# ---------------------------------------------------------------------------


def test_admin_can_share_checkin_link_via_ui(page: Page) -> None:
    admin_token = _make_token("admin")
    _create_session(page, admin_token, "2099-07-29")

    page.set_viewport_size(
        {"width": 375, "height": 667}
    )  # mobile: shows SessionCardList with share button
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Admin sees the "Share check-in link" button (only rendered in mobile SessionCardList)
    share_btn = page.get_by_role("button", name="Share check-in link").first
    expect(share_btn).to_be_visible(timeout=8000)

    share_btn.click()

    # After clicking, a read-only <input> with aria-label="Check-in link" appears.
    # Use a CSS attribute selector to target the input element directly.
    link_input = page.locator('input[aria-label="Check-in link"]').first
    expect(link_input).to_be_visible(timeout=8000)
    link_value = link_input.input_value()
    # `.first` is whichever card the list renders first, not necessarily the
    # one seeded above — so this asserts the link's shape, not its id. That the
    # id is the card's own session is covered without a browser in
    # test_checkin_link_api.py.
    assert re.fullmatch(
        r"https?://[^/]+/checkin/session/[0-9a-f-]{36}", link_value
    ), f"Expected the session's tokenless check-in link, got: {link_value}"


# ---------------------------------------------------------------------------
# AC7 — Admin can see a list of attendees on the Sessions page
# ---------------------------------------------------------------------------


def test_admin_can_view_attendance_list_via_ui(page: Page) -> None:
    """Admin checks in via API then views the attendance list via API (sessions page
    does not expose a per-session attendee list in the UI; the endpoint is tested here
    to verify the data layer is wired correctly and accessible to admins).
    """
    admin_token = _make_token("admin")
    # Start ~30 min from now so the check-in window is open when the member checks in.
    soon = datetime.now() + timedelta(minutes=30)
    session_id = _create_session(
        page, admin_token, soon.strftime("%Y-%m-%d"), start_time=soon.strftime("%H:%M")
    )

    # Check in as a member via API to seed the attendance record
    member_token = _make_token("member")
    checkin_resp = page.request.post(
        f"{API_URL}/sessions/{session_id}/checkin",
        headers=_api_headers(member_token),
    )
    assert (
        checkin_resp.status == 200
    ), f"checkin failed: {checkin_resp.status} {checkin_resp.text()}"

    # Admin retrieves the attendance list
    att_resp = page.request.get(
        f"{API_URL}/sessions/{session_id}/attendance",
        headers=_api_headers(admin_token),
    )
    assert att_resp.status == 200
    records = att_resp.json()
    assert len(records) >= 1, "Expected at least one attendance record"
    assert "member_id" in records[0]
    assert records[0]["session_id"] == session_id


# ---------------------------------------------------------------------------
# AC8 — Check-in UI is thumb-friendly on mobile viewport (not implemented as
#        full UI test — verified via visual layout checks on the sessions page)
# ---------------------------------------------------------------------------


def test_checkin_ui_is_thumb_friendly_on_mobile(page: Page) -> None:
    """At 375px the Check In button meets the 48px min-height thumb-friendly target."""
    admin_token = _make_token("admin")
    _create_session(page, admin_token, "2099-08-19")

    member_token = _make_token("member")
    page.set_viewport_size({"width": 375, "height": 667})
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    check_in_btn = page.get_by_role("button", name="Check In").first
    expect(check_in_btn).to_be_visible(timeout=8000)

    # Verify the button height is at least 48px (thumb-friendly)
    bounding_box = check_in_btn.bounding_box()
    assert bounding_box is not None
    assert (
        bounding_box["height"] >= 48
    ), f"Check In button height {bounding_box['height']}px is less than 48px min"
