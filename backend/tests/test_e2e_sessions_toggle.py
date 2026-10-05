"""
E2E browser tests for issue #93 — List/Calendar segmented toggle on Sessions page.

Acceptance criteria:
  AC1 — List / Calendar toggle appears in the toolbar at md+ breakpoints
  AC2 — Selecting Calendar replaces the content area with CalendarView
  AC3 — Selecting List restores the sessions card list (SessionCardList)
  AC4 — Today's date is highlighted in the calendar (CalendarView integration)
  AC5 — Month view is the default calendar view
  AC6 — Month / week toggle works within calendar view (CalendarView internal)
  AC7 — Clicking a session in calendar navigates to /sessions/:id
  AC8 — Toggle is NOT rendered on mobile; mobile always shows the card list
  AC9 — List is the default view; SessionCardList visible on initial load
"""

import datetime
import json
import uuid

from playwright.sync_api import Page, expect

from app.auth.models import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"
SESSIONS_URL = f"{BASE_URL}/sessions"


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
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


def _go_to_sessions(page: Page, role: str = "member") -> str:
    token = _make_token(role)
    _set_cookie(page, token)
    page.goto(SESSIONS_URL)
    page.wait_for_load_state("networkidle")
    return token


def _create_today_session(page: Page, admin_token: str) -> str:
    types_resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    assert types_resp.status == 200
    type_id = types_resp.json()[0]["id"]
    today = datetime.date.today().isoformat()
    sess_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": "Toggle Test Session",
                "date": today,
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
    assert sess_resp.status == 201
    return sess_resp.json()["id"]


# ---------------------------------------------------------------------------
# AC1 — List / Calendar toggle visible on desktop (md+ breakpoint)
# ---------------------------------------------------------------------------


def test_toggle_buttons_visible_on_desktop(page: Page) -> None:
    """List and Calendar toggle buttons appear in the toolbar at 1280px viewport."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page, "member")

    list_btn = page.get_by_role("button", name="List")
    cal_btn = page.get_by_role("button", name="Calendar")
    expect(list_btn).to_be_visible()
    expect(cal_btn).to_be_visible()

    assert list_btn.get_attribute("aria-pressed") == "true"
    assert cal_btn.get_attribute("aria-pressed") == "false"


# ---------------------------------------------------------------------------
# AC2 — Clicking Calendar renders CalendarView
# ---------------------------------------------------------------------------


def test_clicking_calendar_renders_calendar_view(page: Page) -> None:
    """Clicking the Calendar toggle replaces the sessions card list with CalendarView."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page)

    page.get_by_role("button", name="Calendar").click()
    page.wait_for_load_state("networkidle")

    # CalendarView has prev/next navigation buttons and a period label
    expect(page.get_by_role("button", name="Previous period")).to_be_visible()
    expect(page.get_by_role("button", name="Next period")).to_be_visible()
    expect(page.locator("span.flex-1.text-center")).to_be_visible()

    # Calendar button now active
    assert (
        page.get_by_role("button", name="Calendar").get_attribute("aria-pressed")
        == "true"
    )


# ---------------------------------------------------------------------------
# AC3 — Clicking List restores SessionCardList
# ---------------------------------------------------------------------------


def test_clicking_list_restores_session_card_list(page: Page) -> None:
    """After switching to Calendar, clicking List brings back the session card list."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page)

    # Switch to calendar
    page.get_by_role("button", name="Calendar").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Previous period")).to_be_visible()

    # Switch back to list
    page.get_by_role("button", name="List").click()
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("button", name="Previous period")).not_to_be_visible()
    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    assert (
        page.get_by_role("button", name="List").get_attribute("aria-pressed") == "true"
    )


# ---------------------------------------------------------------------------
# AC4 — Today's date is highlighted in the calendar
# ---------------------------------------------------------------------------


def test_todays_date_highlighted_in_calendar(page: Page) -> None:
    """When CalendarView is shown, today's date cell is visually highlighted."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page)

    page.get_by_role("button", name="Calendar").click()
    page.wait_for_load_state("networkidle")

    today_day = str(datetime.date.today().day)
    today_el = page.locator("span.bg-primary.text-primary-foreground").first
    expect(today_el).to_be_visible(timeout=10000)
    assert today_el.inner_text().strip() == today_day


# ---------------------------------------------------------------------------
# AC5 — Month view is the default when CalendarView is first shown
# ---------------------------------------------------------------------------


def test_calendar_defaults_to_month_view(page: Page) -> None:
    """When the Calendar toggle is selected, month view (grid with day headers) is shown."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page)

    page.get_by_role("button", name="Calendar").click()
    page.wait_for_load_state("networkidle")

    # Month grid has day-of-week headers
    expect(page.get_by_text("Mon", exact=True).first).to_be_visible()
    expect(page.get_by_text("Tue", exact=True).first).to_be_visible()

    # Month button inside CalendarView is active
    month_btn = page.get_by_role("button", name="Month")
    expect(month_btn).to_be_visible()
    assert month_btn.get_attribute("aria-pressed") == "true"


# ---------------------------------------------------------------------------
# AC6 — Month / week toggle works within the CalendarView
# ---------------------------------------------------------------------------


def test_month_week_toggle_works_in_calendar_view(page: Page) -> None:
    """Month/Week buttons inside CalendarView switch between month and week grids."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page)

    page.get_by_role("button", name="Calendar").click()
    page.wait_for_load_state("networkidle")

    week_btn = page.get_by_role("button", name="Week")
    month_btn = page.get_by_role("button", name="Month")

    week_btn.click()
    page.wait_for_load_state("networkidle")
    assert week_btn.get_attribute("aria-pressed") == "true"
    assert month_btn.get_attribute("aria-pressed") == "false"

    month_btn.click()
    page.wait_for_load_state("networkidle")
    assert month_btn.get_attribute("aria-pressed") == "true"


# ---------------------------------------------------------------------------
# AC7 — Clicking a session in the calendar navigates to /sessions/:id
# ---------------------------------------------------------------------------


def test_clicking_session_in_calendar_navigates_to_session_detail(page: Page) -> None:
    """A session chip in CalendarView navigates to /sessions/:id on click."""
    admin_token = _make_token("admin")
    session_id = _create_today_session(page, admin_token)

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(SESSIONS_URL)
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Calendar").click()
    page.wait_for_load_state("networkidle")

    chip = page.locator(f'[data-session-id="{session_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    chip.click()
    expect(page).to_have_url(f"{BASE_URL}/sessions/{session_id}", timeout=10000)


# ---------------------------------------------------------------------------
# AC8 — Toggle is NOT rendered on mobile; mobile always shows the card list
# ---------------------------------------------------------------------------


def test_toggle_hidden_on_mobile_viewport(page: Page) -> None:
    """The List/Calendar toggle is not visible at 375px mobile viewport width."""
    page.set_viewport_size({"width": 375, "height": 667})
    _go_to_sessions(page)

    expect(page.get_by_role("button", name="List")).not_to_be_visible()
    expect(page.get_by_role("button", name="Calendar")).not_to_be_visible()


def test_mobile_always_shows_session_card_list(page: Page) -> None:
    """On mobile (375px), the sessions list is shown (no calendar navigation)."""
    page.set_viewport_size({"width": 375, "height": 667})
    _go_to_sessions(page)

    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    expect(page.get_by_role("button", name="Previous period")).not_to_be_visible()


# ---------------------------------------------------------------------------
# AC9 — List is the default view on initial page load
# ---------------------------------------------------------------------------


def test_list_is_default_view_on_sessions_page(page: Page) -> None:
    """SessionCardList is visible by default; CalendarView nav is not shown on load."""
    page.set_viewport_size({"width": 1280, "height": 800})
    _go_to_sessions(page)

    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    expect(page.get_by_role("button", name="Previous period")).not_to_be_visible()
    assert (
        page.get_by_role("button", name="List").get_attribute("aria-pressed") == "true"
    )
