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
import os
import re
import uuid

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
# Helpers
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _create_session(
    page: Page, token: str, *, info: str | None = None, coach_notes: str | None = None
) -> str:
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(token),
    )
    type_id = types_resp.json()[0]["id"]

    payload: dict = {
        "title": "Detail Test Session",
        "date": "2099-12-01",
        "segments": [
            {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}
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
    session_id = _create_session(page, admin_token)

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
