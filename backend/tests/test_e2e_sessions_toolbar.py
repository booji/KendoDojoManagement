"""
E2E browser tests for issue #92 — page toolbar + SessionCardList extraction.
"""

from __future__ import annotations

import uuid

from playwright.sync_api import Page, expect

from app.auth.models import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth helpers
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
    """Navigate to the app and set the access_token cookie."""
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _go_to_sessions_as(page: Page, role: str) -> None:
    token = _make_token(role)
    _set_cookie(page, token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------
# Test: SessionCardList renders week-grouped cards
# ---------------------------------------------------------------------------


def test_session_card_list_renders_week_grouped_cards(page: Page) -> None:
    """SessionCardList renders week-grouped cards with check-in/share/attendance."""
    admin_token = _make_token("admin")
    headers = {**_api_headers(admin_token), "Content-Type": "application/json"}

    # Get a session type
    import json

    types_resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    assert types_resp.status == 200
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    # Seed a session far in the future
    page.request.post(
        f"{API_URL}/sessions",
        headers=headers,
        data=json.dumps(
            {
                "title": type_name,
                "date": "2099-07-14",
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 90,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )

    # Use mobile viewport so SessionCardList (md:hidden) is visible, not the table
    page.set_viewport_size({"width": 375, "height": 812})
    _go_to_sessions_as(page, "member")

    # Week group label (h2) should be present
    week_labels = page.locator("h2").all()
    assert len(week_labels) >= 1, "Expected at least one week group label"

    # Session type name visible as a card heading
    expect(page.get_by_text(type_name).first).to_be_visible()


# ---------------------------------------------------------------------------
# Test: SessionsPage delegates to SessionCardList
# ---------------------------------------------------------------------------


def test_sessions_page_renders_session_card_list(page: Page) -> None:
    """SessionsPage delegates to SessionCardList and output is identical."""
    _go_to_sessions_as(page, "member")

    # Page heading is present
    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()

    # The toolbar row is present (contains the calendar icon button)
    expect(page.get_by_role("button", name="Subscribe to iCal feed")).to_be_visible()


# ---------------------------------------------------------------------------
# Test: iCal card removed; toolbar calendar icon opens popover
# ---------------------------------------------------------------------------


def test_ical_card_removed_toolbar_icon_opens_popover(page: Page) -> None:
    """iCal card is gone; toolbar calendar icon opens popover with URL and copy button."""
    _go_to_sessions_as(page, "member")

    # There should be NO standalone card element with ical URL text visible
    # before clicking the popover button.
    ical_url_text = page.get_by_text("/api/sessions/ical")
    expect(ical_url_text).not_to_be_visible()

    # The toolbar iCal icon button is visible
    ical_btn = page.get_by_role("button", name="Subscribe to iCal feed")
    expect(ical_btn).to_be_visible()

    # Click it and the popover should appear with the URL input and Copy button
    ical_btn.click()
    # Role-scoped rather than get_by_label: the copy button beside this input
    # is named "Copy iCal feed URL" (#367), and get_by_label matches on
    # substring, so a bare label lookup now resolves to both.
    expect(page.get_by_role("textbox", name="iCal feed URL")).to_be_visible()
    expect(page.get_by_role("button", name="Copy iCal feed URL")).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Create Session button visible in toolbar for admin
# ---------------------------------------------------------------------------


def test_create_session_button_visible_in_toolbar_for_admin(page: Page) -> None:
    """Admin sees Create Session button in the toolbar."""
    _go_to_sessions_as(page, "admin")

    # The Create Session dialog trigger button is in the toolbar
    expect(page.get_by_role("button", name="Create Session")).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Toolbar visible on desktop and mobile
# ---------------------------------------------------------------------------


def test_toolbar_visible_on_desktop_and_mobile(page: Page) -> None:
    """Toolbar is visible at 1280px width and 375px width."""
    # Desktop
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions_as(page, "member")
    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    expect(page.get_by_role("button", name="Subscribe to iCal feed")).to_be_visible()

    # Mobile
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    expect(page.get_by_role("button", name="Subscribe to iCal feed")).to_be_visible()


# ---------------------------------------------------------------------------
# Test: No layout breakage on mobile
# ---------------------------------------------------------------------------


def test_sessions_page_no_visual_regression_mobile(page: Page) -> None:
    """Sessions page layout is correct on 375px mobile viewport."""
    page.set_viewport_size({"width": 375, "height": 667})
    _go_to_sessions_as(page, "member")

    # Page heading visible and not clipped
    heading = page.get_by_role("heading", name="Sessions")
    expect(heading).to_be_visible()

    # iCal button visible and within viewport
    ical_btn = page.get_by_role("button", name="Subscribe to iCal feed")
    expect(ical_btn).to_be_visible()
    btn_box = ical_btn.bounding_box()
    assert btn_box is not None, "iCal button bounding box should not be None"
    assert btn_box["x"] >= 0, "iCal button should not overflow left edge"
    assert (
        btn_box["x"] + btn_box["width"] <= 375 + 1
    ), f"iCal button overflows right edge: x={btn_box['x']}, width={btn_box['width']}"
