"""
Playwright browser tests for issue #56 — Sessions page polish + iCal copy widget.

Acceptance criteria:
  1. Clicking a session card navigates to /sessions/:id
  2. iCal URL is displayed on the Sessions page for all authenticated users
  3. Copy button copies the iCal URL to the clipboard
  4. Helper text is present ("Subscribe in Google Calendar, Apple Calendar, or Outlook…")
  5. E2E: user clicks copy button and URL is in clipboard;
          user clicks a session card and lands on the detail page
"""

from __future__ import annotations

import json
import os
import re
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# Load the real JWT_SECRET from .env so tokens pass server-side validation.
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
# Auth helpers (same pattern as test_e2e_sessions.py)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}@dojo.test",
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


def _ensure_session(page: Page, admin_token: str) -> str:
    """Create a far-future ad-hoc session and return its id."""
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    assert types_resp.status == 200
    type_id = types_resp.json()[0]["id"]

    sess_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "session_type_id": type_id,
                "date": "2099-07-15",
                "start_time": "19:00",
                "duration_minutes": 90,
            }
        ),
    )
    assert (
        sess_resp.status == 201
    ), f"Expected 201, got {sess_resp.status}: {sess_resp.text()}"
    return sess_resp.json()["id"]


# ---------------------------------------------------------------------------
# AC1 — Clicking a session card navigates to /sessions/:id
# ---------------------------------------------------------------------------


def test_session_card_click_navigates_to_detail_page(page: Page) -> None:
    """Clicking any session card on the Sessions page navigates to /sessions/:id."""
    admin_token = _make_token("admin")
    session_id = _ensure_session(page, admin_token)

    member_token = _make_token("member")
    page.set_viewport_size({"width": 375, "height": 812})
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Click the first session card (mobile card list visible at 375px)
    card = page.locator(".cursor-pointer").first
    expect(card).to_be_visible()
    card.click()

    # Should land on /sessions/<uuid>
    expect(page).to_have_url(re.compile(r"/sessions/[0-9a-f-]{36}$"), timeout=5000)


# ---------------------------------------------------------------------------
# AC2 — iCal URL is displayed on the Sessions page for all authenticated users
# ---------------------------------------------------------------------------


def test_ical_url_displayed_for_authenticated_member(page: Page) -> None:
    """An authenticated member visiting the Sessions page sees the iCal subscription URL."""
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # The iCal input is inside a popover — open it first
    page.get_by_role("button", name="Subscribe to iCal feed").click()

    ical_input = page.get_by_label("iCal feed URL")
    expect(ical_input).to_be_visible()

    url_value = ical_input.input_value()
    assert (
        "/api/sessions/ical" in url_value
    ), f"Expected iCal URL to contain '/api/sessions/ical', got: {url_value}"


# ---------------------------------------------------------------------------
# AC3 — Copy button copies the iCal URL to the clipboard
# ---------------------------------------------------------------------------


def test_ical_copy_button_copies_url_to_clipboard(page: Page) -> None:
    """Clicking the copy button puts the iCal URL into the browser clipboard."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])

    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Open the iCal popover first
    page.get_by_role("button", name="Subscribe to iCal feed").click()

    copy_button = page.get_by_role("button", name="Copy")
    expect(copy_button).to_be_visible()
    copy_button.click()

    # Button text should change to "Copied!"
    expect(page.get_by_role("button", name="Copied!")).to_be_visible()

    # The clipboard should contain the iCal URL
    clipboard_text = page.evaluate("navigator.clipboard.readText()")
    assert (
        "/api/sessions/ical" in clipboard_text
    ), f"Expected clipboard to contain iCal URL, got: {clipboard_text}"


# ---------------------------------------------------------------------------
# AC4 — Helper text is present
# ---------------------------------------------------------------------------


def test_ical_widget_shows_helper_text(page: Page) -> None:
    """The iCal widget displays helper text about subscribing in calendar apps."""
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Open the iCal popover first
    page.get_by_role("button", name="Subscribe to iCal feed").click()

    helper = page.get_by_text(
        "Subscribe in Google Calendar, Apple Calendar, or Outlook using this URL"
    )
    expect(helper).to_be_visible()


# ---------------------------------------------------------------------------
# AC5 — E2E: copy button puts URL in clipboard; session card lands on detail page
# ---------------------------------------------------------------------------


def test_e2e_copy_then_navigate_to_session_detail(page: Page) -> None:
    """Full E2E: user clicks copy button (URL lands in clipboard), then clicks
    a session card and lands on /sessions/:id detail page."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])

    admin_token = _make_token("admin")
    session_id = _ensure_session(page, admin_token)

    member_token = _make_token("member")
    page.set_viewport_size({"width": 375, "height": 812})
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Part 1: copy iCal URL to clipboard (open popover first)
    page.get_by_role("button", name="Subscribe to iCal feed").click()
    copy_button = page.get_by_role("button", name="Copy")
    expect(copy_button).to_be_visible()
    copy_button.click()
    expect(page.get_by_role("button", name="Copied!")).to_be_visible()

    clipboard_text = page.evaluate("navigator.clipboard.readText()")
    assert (
        "/api/sessions/ical" in clipboard_text
    ), f"Clipboard should contain iCal URL, got: {clipboard_text}"

    # Close popover and navigate to session detail via card click (mobile card list at 375px)
    page.keyboard.press("Escape")
    # Part 2: navigate to session detail via card click (mobile card list at 375px)
    card = page.locator(".cursor-pointer").first
    expect(card).to_be_visible()
    card.click()

    # Any session detail page is valid — other sessions may exist from prior runs
    expect(page).to_have_url(re.compile(r"/sessions/[0-9a-f-]{36}$"), timeout=5000)
