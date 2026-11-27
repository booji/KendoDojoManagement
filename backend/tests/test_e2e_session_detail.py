"""
E2E browser tests for session detail page layout (PR #141).

Covers:
  AC9  — Admin sees coach_notes; member does not
  AC10 — Member checks in from the session detail page
  Layout — Attendance collapsible collapsed by default, expands on click
  Layout — Admin action buttons are right-aligned
  Layout — Info and coach notes render side-by-side on desktop when both present
"""

import json
import re
import uuid
from datetime import datetime, timedelta

from playwright.sync_api import Page, expect

from app.auth.schemas import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
    )
    token = login_as(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _create_session(
    page: Page,
    token: str,
    *,
    info: str | None = None,
    coach_notes: str | None = None,
    date: str = "2099-12-01",
    start_time: str = "19:00",
) -> str:
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(token),
    )
    type_id = types_resp.json()[0]["id"]

    payload: dict = {
        "title": "Detail Test Session",
        "date": date,
        "segments": [
            {"start_time": start_time, "duration_minutes": 90, "type_ids": [type_id]}
        ],
    }
    if info is not None:
        payload["info"] = info
    if coach_notes is not None:
        payload["coach_notes"] = coach_notes

    resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status == 201, f"Session create failed: {resp.text()}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# AC9 — Admin sees coach_notes; member does not
# ---------------------------------------------------------------------------


def test_admin_sees_coach_notes_on_session_detail_page(page: Page) -> None:
    admin_token = _make_token("admin")
    session_id = _create_session(
        page,
        admin_token,
        info="Public info here",
        coach_notes="Secret coach note",
    )

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text("Coach Notes")).to_be_visible()
    expect(page.get_by_text("Secret coach note")).to_be_visible()


def test_member_does_not_see_coach_notes_on_session_detail_page(page: Page) -> None:
    admin_token = _make_token("admin")
    session_id = _create_session(
        page,
        admin_token,
        info="Public info here",
        coach_notes="Secret coach note",
    )

    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text("Public info here")).to_be_visible()
    expect(page.get_by_text("Secret coach note")).not_to_be_visible()


# ---------------------------------------------------------------------------
# AC10 — Member checks in from the session detail page
# ---------------------------------------------------------------------------


def test_member_can_check_in_from_session_detail_page(page: Page) -> None:
    admin_token = _make_token("admin")
    # The check-in window (default: opens 60 min before start) must be open, so
    # schedule the session to start ~30 min from now rather than far in the future.
    soon = datetime.now() + timedelta(minutes=30)
    session_id = _create_session(
        page,
        admin_token,
        date=soon.strftime("%Y-%m-%d"),
        start_time=soon.strftime("%H:%M"),
    )

    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Check In").click()
    expect(page.get_by_text("Checked in!")).to_be_visible()


# ---------------------------------------------------------------------------
# Layout — Attendance collapsible
# ---------------------------------------------------------------------------


def test_attendance_section_is_collapsed_by_default(page: Page) -> None:
    admin_token = _make_token("admin")
    session_id = _create_session(page, admin_token)

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")

    # Trigger button visible, list not visible
    expect(page.get_by_role("button", name=re.compile("Attendance"))).to_be_visible()
    expect(page.get_by_label("Attendance list")).not_to_be_visible()


def test_attendance_section_expands_on_click(page: Page) -> None:
    admin_token = _make_token("admin")
    session_id = _create_session(page, admin_token)

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name=re.compile("Attendance")).click()
    expect(page.get_by_text("No attendees yet.")).to_be_visible()


# ---------------------------------------------------------------------------
# Layout — Admin action buttons right-aligned
# ---------------------------------------------------------------------------


def test_admin_action_buttons_are_right_aligned(page: Page) -> None:
    admin_token = _make_token("admin")
    session_id = _create_session(page, admin_token)

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")

    page.set_viewport_size({"width": 1280, "height": 800})

    edit_btn = page.get_by_role("button", name="Edit")
    cancel_btn = page.get_by_role("button", name="Cancel Session")

    expect(edit_btn).to_be_visible()
    expect(cancel_btn).to_be_visible()

    # Edit (primary/safe) must be to the right of Cancel Session (destructive)
    edit_x = edit_btn.bounding_box()["x"]
    cancel_x = cancel_btn.bounding_box()["x"]
    assert edit_x > cancel_x, "Edit button should be to the right of Cancel Session"


# ---------------------------------------------------------------------------
# Issue #429 — changing the Date in the edit form moves the session
# ---------------------------------------------------------------------------


def test_editing_the_date_moves_the_session_on_the_calendar(page: Page) -> None:
    # Both dates in the current month, so the home calendar shows them unpaged.
    today = datetime.now().date()
    old_date, new_date = today.replace(day=10), today.replace(day=20)
    admin_token = _make_token("admin")
    session_id = _create_session(page, admin_token, date=old_date.isoformat())

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.get_by_role("button", name="Edit").click()
    page.locator("#edit-date").fill(new_date.isoformat())
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("button", name="Edit")).to_be_visible()

    page.goto(BASE_URL)
    chip = page.locator(f'[data-session-id="{session_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    # The chip's day cell leads with its day-of-month number.
    expect(chip.locator("xpath=..").locator("span").first).to_have_text("20")


# ---------------------------------------------------------------------------
# Issue #579 — cancelling asks first, and a Cancellation can be undone
# ---------------------------------------------------------------------------


def _is_cancelled(page: Page, token: str, session_id: str) -> bool:
    resp = page.request.get(
        f"{API_URL}/sessions/{session_id}", headers=_api_headers(token)
    )
    return resp.json()["cancelled"]


def test_cancelling_a_session_asks_first_and_can_be_reinstated(page: Page) -> None:
    admin_token = _make_token("admin")
    session_id = _create_session(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")

    # Backing out of the dialog cancels nothing.
    page.get_by_role("button", name="Cancel Session").click()
    dialog = page.get_by_role("dialog")
    cancel = dialog.get_by_role("button", name="Cancel", exact=True)
    expect(cancel).to_be_focused()
    cancel.click()
    expect(dialog).to_be_hidden()
    assert not _is_cancelled(page, admin_token, session_id)

    page.get_by_role("button", name="Cancel Session").click()
    dialog.get_by_role("button", name="Cancel session").click()
    expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Cancel Session")).to_have_count(0)
    assert _is_cancelled(page, admin_token, session_id)

    page.get_by_role("button", name="Reinstate Session").click()
    expect(page.get_by_role("button", name="Cancel Session")).to_be_visible()
    expect(page.get_by_text("Cancelled", exact=True)).to_have_count(0)
    assert not _is_cancelled(page, admin_token, session_id)


def test_cancelling_a_series_asks_first_and_shows_the_session_cancelled(
    page: Page,
) -> None:
    admin_token = _make_token("admin")
    type_id = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    ).json()[0]["id"]
    resp = page.request.post(
        f"{API_URL}/sessions/templates",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": "Series To Cancel",
                "start_date": "2099-03-02",
                "end_date": "2099-03-20",
                "recurrence_days": [0],
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 60,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert resp.status == 201, resp.text()
    template_id = resp.json()["id"]
    sessions = page.request.get(
        f"{API_URL}/sessions", headers=_api_headers(admin_token)
    ).json()
    session_id = next(s["id"] for s in sessions if s["template_id"] == template_id)

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.get_by_role("button", name="Cancel Series").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
    assert not _is_cancelled(page, admin_token, session_id)

    dialog.get_by_role("button", name="Cancel series").click()
    expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Cancel Series")).to_have_count(0)
    assert _is_cancelled(page, admin_token, session_id)
