"""
Browser (Playwright) tests for issue #11 — Reports and CSV export.

One test per acceptance criterion.
Auth pattern: signed in through the test-login endpoint (tests.e2e_support.login_as),
which creates a real Account and its Member; the session cookie is set on the page.
"""

import uuid

from playwright.sync_api import Page, expect

from app.auth.schemas import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
    )
    token = login_as(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


# ---------------------------------------------------------------------------
# AC1 — Reports UI renders attendance report with session data
# ---------------------------------------------------------------------------


def test_reports_page_renders_attendance_report(page: Page) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}/reports")

    # The page heading is visible
    expect(page.get_by_role("heading", name="Reports")).to_be_visible()

    # Reports opens on Charts, the first tab (#607)
    tabs = page.get_by_role("tab")
    expect(tabs.first).to_have_text("Charts")
    expect(page.get_by_role("tab", name="Charts")).to_have_attribute(
        "aria-selected", "true"
    )

    page.get_by_role("tab", name="Attendance").click()

    # The Generate button is visible on the attendance tab
    expect(
        page.get_by_role("button", name="Generate attendance report")
    ).to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — CSV download buttons are present and trigger download
# ---------------------------------------------------------------------------


def test_reports_page_has_csv_download_buttons(page: Page) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}/reports")
    page.get_by_role("tab", name="Attendance").click()

    # Attendance tab: Download CSV button is present (disabled until report generated)
    expect(page.get_by_role("button", name="Download attendance CSV")).to_be_visible()

    # The Members tab is gone: its CSV is downloaded from /members (#571)
    expect(page.get_by_role("tab", name="Members")).to_have_count(0)


# ---------------------------------------------------------------------------
# AC4 — Reports page is navigable from the main UI (route exists)
# ---------------------------------------------------------------------------


def test_reports_page_is_accessible_via_navigation(page: Page) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}/")
    page.wait_for_selector("[data-slot='sidebar']", timeout=15000)

    # Reports link is visible in the sidebar nav
    reports_link = page.get_by_role("link", name="Reports")
    expect(reports_link).to_be_visible()

    reports_link.click()
    expect(page).to_have_url(f"{BASE_URL}/reports")
    expect(page.get_by_role("heading", name="Reports")).to_be_visible()


# ---------------------------------------------------------------------------
# AC5 — Unauthenticated users are redirected away from the reports page
# ---------------------------------------------------------------------------


def test_reports_page_redirects_unauthenticated_users(page: Page) -> None:
    import re

    # Visit /reports with no auth cookie
    page.goto(f"{BASE_URL}/reports")

    # Redirects to /login (app set up) or /setup (no credentials yet)
    expect(page).to_have_url(re.compile(r"/(login|setup)$"), timeout=10000)
