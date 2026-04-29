"""
E2E browser tests for issue #55 — Calendar view.

Acceptance criteria stubs (red phase — all xfail strict):
  2. Month grid renders sessions as titled chips
  3. Week grid renders sessions with title and time
  4. Toggle switches between month and week view
  5. Agenda list renders automatically on narrow viewports
  6. Clicking a session chip navigates to /sessions/:id
  7. Month/week navigation (prev/next) works correctly
  8. Cancelled sessions are visually distinguished for admins; hidden from members
  9. Home dashboard uses the calendar component and fetches from GET /sessions?from=&to=
  10. E2E: admin sees all sessions including cancelled (distinguished); member sees only active
"""

import json
import os
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=True)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

# Use a far-future month that is guaranteed to have no existing sessions.
# Tests that need calendar navigation will navigate to this month.
# Format: "YYYY-MM-DD"
_TEST_DATE = "2090-06-15"  # a Sunday in June 2090
_TEST_MONTH_LABEL = "June 2090"
_TEST_PREV_MONTH_LABEL = "May 2090"
_TEST_NEXT_MONTH_LABEL = "July 2090"
_TEST_TIME = "19:00"


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


def _create_test_session(page: Page, admin_token: str, date: str = _TEST_DATE) -> dict:
    """Create an ad-hoc session on `date` and return the session JSON with type_name."""
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    assert types_resp.status == 200
    session_type = types_resp.json()[0]
    type_id = session_type["id"]

    sess_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "session_type_id": type_id,
                "date": date,
                "start_time": _TEST_TIME,
                "duration_minutes": 90,
            }
        ),
    )
    assert (
        sess_resp.status == 201
    ), f"Expected 201, got {sess_resp.status}: {sess_resp.text()}"
    session = sess_resp.json()
    session["type_name"] = session_type["name"]
    return session


def _navigate_to_test_month(page: Page) -> None:
    """Navigate the calendar forward until _TEST_MONTH_LABEL is shown in the toolbar."""
    period_span = page.locator("span.flex-1.text-center")
    for _ in range(900):  # 2090 is ~75 years = ~900 months from 2026
        label = period_span.inner_text(timeout=5000)
        if label == _TEST_MONTH_LABEL:
            return
        page.get_by_role("button", name="Next period").click()
        page.wait_for_timeout(30)  # brief pause; don't hammer too hard
    raise AssertionError(f"Could not navigate to {_TEST_MONTH_LABEL}")


def _navigate_fast(page: Page, target_label: str) -> None:
    """Use API to load the page with ?month= parameter if supported, else navigate via clicks.

    Since the CalendarView uses anchor state (no URL params), we use JavaScript to
    manipulate the anchor by dispatching a known number of clicks.
    """
    # Count clicks from current month (April 2026) to June 2090:
    # 2090-06 - 2026-04 = 64 years * 12 + 2 months = 770 months
    _MONTHS_AHEAD = (2090 - 2026) * 12 + (6 - 4)  # 770
    period_span = page.locator("span.flex-1.text-center")
    next_btn = page.get_by_role("button", name="Next period")
    for _ in range(_MONTHS_AHEAD):
        next_btn.click()
        page.wait_for_timeout(10)
    # Verify we landed correctly
    actual = period_span.inner_text(timeout=5000)
    assert actual == target_label, f"Expected '{target_label}', got '{actual}'"


# ---------------------------------------------------------------------------
# AC2 — Month grid renders sessions as titled chips
# ---------------------------------------------------------------------------


def test_month_grid_renders_session_chips(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _create_test_session(page, admin_token)
    type_name = session["type_name"]

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Navigate to the test month
    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    # Session chip renders with aria-label containing the type name
    chip = page.get_by_role("button", name=type_name, exact=False).first
    expect(chip).to_be_visible(timeout=10000)


# ---------------------------------------------------------------------------
# AC3 — Week grid renders sessions with title and time
# ---------------------------------------------------------------------------


def test_week_grid_renders_sessions_with_title_and_time(page: Page) -> None:
    import datetime

    today = datetime.date.today().isoformat()

    admin_token = _make_token("admin")
    # Create session for today so it's visible in the current week — no navigation needed.
    session = _create_test_session(page, admin_token, date=today)
    type_name = session["type_name"]

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Switch to week view — today's session should be visible immediately.
    page.get_by_role("button", name="Week").click()
    page.wait_for_load_state("networkidle")

    # Week grid chips show aria-label "{type_name} at {time}"
    chip = page.locator(f'[data-session-id="{session["id"]}"]')
    expect(chip).to_be_visible(timeout=10000)

    label = chip.get_attribute("aria-label") or ""
    assert (
        _TEST_TIME in label
    ), f"Expected '{_TEST_TIME}' in chip aria-label, got: {label!r}"


# ---------------------------------------------------------------------------
# AC4 — Toggle switches between month and week view
# ---------------------------------------------------------------------------


def test_view_toggle_switches_between_month_and_week(page: Page) -> None:
    admin_token = _make_token("admin")

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    month_btn = page.get_by_role("button", name="Month")
    week_btn = page.get_by_role("button", name="Week")
    expect(month_btn).to_be_visible()
    expect(week_btn).to_be_visible()
    assert (
        month_btn.get_attribute("aria-pressed") == "true"
    ), "Month should be active initially"

    week_btn.click()
    page.wait_for_load_state("networkidle")

    assert (
        week_btn.get_attribute("aria-pressed") == "true"
    ), "Week should be active after click"
    assert (
        month_btn.get_attribute("aria-pressed") == "false"
    ), "Month should be inactive after switching to Week"

    month_btn.click()
    page.wait_for_load_state("networkidle")

    assert (
        month_btn.get_attribute("aria-pressed") == "true"
    ), "Month should be active again"


# ---------------------------------------------------------------------------
# AC5 — Agenda list renders automatically on narrow viewports
# ---------------------------------------------------------------------------


def test_agenda_list_renders_on_narrow_viewport(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _create_test_session(page, admin_token)
    type_name = session["type_name"]

    # Set narrow (mobile) viewport
    page.set_viewport_size({"width": 375, "height": 667})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # On narrow viewport, Month/Week toggle is hidden (hidden md:flex)
    month_btn = page.get_by_role("button", name="Month")
    expect(month_btn).not_to_be_visible()

    # AgendaView renders — navigate to the test month and check
    # On mobile, clicking next navigates by month
    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    # Agenda items are rendered as buttons with the session type name
    agenda_item = page.get_by_role("button", name=type_name, exact=False).first
    expect(agenda_item).to_be_visible(timeout=10000)


# ---------------------------------------------------------------------------
# AC6 — Clicking a session chip navigates to /sessions/:id
# ---------------------------------------------------------------------------


def test_clicking_session_chip_navigates_to_session_detail(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _create_test_session(page, admin_token)
    session_id = session["id"]
    type_name = session["type_name"]

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    chip = page.locator(f'[data-session-id="{session_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    chip.click()

    expect(page).to_have_url(f"{BASE_URL}/sessions/{session_id}", timeout=10000)


# ---------------------------------------------------------------------------
# AC7 — Month/week navigation (prev/next) works correctly
# ---------------------------------------------------------------------------


def test_prev_next_navigation_changes_displayed_period(page: Page) -> None:
    admin_token = _make_token("admin")

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Navigate forward to the test month
    _navigate_fast(page, _TEST_MONTH_LABEL)

    period_span = page.locator("span.flex-1.text-center")
    expect(period_span).to_have_text(_TEST_MONTH_LABEL, timeout=5000)

    # Click Next — should go to July 2090
    page.get_by_role("button", name="Next period").click()
    page.wait_for_load_state("networkidle")
    expect(period_span).to_have_text(_TEST_NEXT_MONTH_LABEL, timeout=5000)

    # Click Prev twice — should land on May 2090
    page.get_by_role("button", name="Previous period").click()
    page.wait_for_load_state("networkidle")
    expect(period_span).to_have_text(_TEST_MONTH_LABEL, timeout=5000)

    page.get_by_role("button", name="Previous period").click()
    page.wait_for_load_state("networkidle")
    expect(period_span).to_have_text(_TEST_PREV_MONTH_LABEL, timeout=5000)


# ---------------------------------------------------------------------------
# AC8 — Cancelled sessions are visually distinguished for admins; hidden from members
# ---------------------------------------------------------------------------


def test_cancelled_sessions_distinguished_for_admin_hidden_for_member(
    page: Page,
) -> None:
    admin_token = _make_token("admin")
    session = _create_test_session(page, admin_token)
    session_id = session["id"]
    type_name = session["type_name"]

    # Cancel the session via API
    cancel_resp = page.request.post(
        f"{API_URL}/sessions/{session_id}/cancel",
        headers=_api_headers(admin_token),
    )
    assert cancel_resp.status == 200

    # Admin view on desktop month grid
    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    # The chip has aria-label "{type_name} (cancelled)"
    cancelled_chip = page.get_by_role(
        "button", name=f"{type_name} (cancelled)", exact=False
    ).first
    expect(cancelled_chip).to_be_visible(timeout=10000)

    # Verify line-through class
    class_attr = cancelled_chip.get_attribute("class") or ""
    assert (
        "line-through" in class_attr
    ), f"Expected 'line-through' in class: {class_attr!r}"

    # Member view: cancelled session should NOT appear
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    cancelled_chip_member = page.get_by_role(
        "button", name=f"{type_name} (cancelled)", exact=False
    )
    expect(cancelled_chip_member).to_have_count(0, timeout=10000)


# ---------------------------------------------------------------------------
# AC9 — Home dashboard uses the calendar component and fetches from GET /sessions?from=&to=
# ---------------------------------------------------------------------------


def test_home_dashboard_uses_calendar_and_fetches_range(page: Page) -> None:
    admin_token = _make_token("admin")

    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)

    # Capture network requests to verify range fetching
    requests_seen: list[str] = []

    def capture_request(request) -> None:  # type: ignore[no-untyped-def]
        if "/sessions" in request.url and "from=" in request.url:
            requests_seen.append(request.url)

    page.on("request", capture_request)

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Toolbar: prev/next buttons visible
    expect(page.get_by_role("button", name="Previous period")).to_be_visible()
    expect(page.get_by_role("button", name="Next period")).to_be_visible()

    # Month/Week toggle visible on desktop
    expect(page.get_by_role("button", name="Month")).to_be_visible()
    expect(page.get_by_role("button", name="Week")).to_be_visible()

    # Day-of-week headers rendered in the month grid (exact=True avoids matching agenda h2s)
    expect(page.get_by_text("Mon", exact=True).first).to_be_visible()
    expect(page.get_by_text("Tue", exact=True).first).to_be_visible()

    # At least one range request was made
    assert (
        len(requests_seen) > 0
    ), "Expected at least one /sessions?from=...&to=... request, got none."


# ---------------------------------------------------------------------------
# AC10 — E2E: admin sees all sessions including cancelled; member sees only active
# ---------------------------------------------------------------------------


def test_admin_sees_cancelled_sessions_member_sees_only_active(page: Page) -> None:
    admin_token = _make_token("admin")
    session = _create_test_session(page, admin_token)
    session_id = session["id"]
    type_name = session["type_name"]

    # Cancel the session
    cancel_resp = page.request.post(
        f"{API_URL}/sessions/{session_id}/cancel",
        headers=_api_headers(admin_token),
    )
    assert cancel_resp.status == 200

    # --- Admin sees the cancelled session (distinguished) ---
    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    admin_cancelled_chip = page.get_by_role(
        "button", name=f"{type_name} (cancelled)", exact=False
    ).first
    expect(admin_cancelled_chip).to_be_visible(timeout=10000)

    # --- Member does NOT see the cancelled session ---
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    _navigate_fast(page, _TEST_MONTH_LABEL)
    page.wait_for_load_state("networkidle")

    member_cancelled_chip = page.get_by_role(
        "button", name=f"{type_name} (cancelled)", exact=False
    )
    expect(member_cancelled_chip).to_have_count(0, timeout=10000)

    # Also confirm via API: member-accessible /sessions should not include the cancelled one
    member_sessions_resp = page.request.get(
        f"{API_URL}/sessions",
        headers=_api_headers(member_token),
    )
    assert member_sessions_resp.status == 200
    member_ids = [s["id"] for s in member_sessions_resp.json()]
    assert (
        session_id not in member_ids
    ), f"Cancelled session {session_id} should not appear in member's session list"
