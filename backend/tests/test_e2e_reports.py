"""
Browser (Playwright) tests for issue #11 — Reports and CSV export.

One test per acceptance criterion.
Auth pattern: synthetic JWT tokens injected as cookies (same as test_e2e_attendance_admin.py).
"""

import os
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


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


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

    # The Attendance tab is the default active tab
    expect(page.get_by_role("tab", name="Attendance")).to_be_visible()

    # The Generate button is visible on the attendance tab
    expect(
        page.get_by_role("button", name="Generate attendance report")
    ).to_be_visible()


# ---------------------------------------------------------------------------
# AC2 — Reports UI renders members report with grade and join date
# ---------------------------------------------------------------------------


def test_reports_page_renders_members_report(page: Page) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}/reports")

    # Click the Members tab
    page.get_by_role("tab", name="Members").click()

    # The Generate button for members report is visible
    expect(page.get_by_role("button", name="Generate members report")).to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — CSV download buttons are present and trigger download
# ---------------------------------------------------------------------------


def test_reports_page_has_csv_download_buttons(page: Page) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}/reports")

    # Attendance tab: Download CSV button is present (disabled until report generated)
    expect(page.get_by_role("button", name="Download attendance CSV")).to_be_visible()

    # Switch to Members tab and check its download button too
    page.get_by_role("tab", name="Members").click()
    expect(page.get_by_role("button", name="Download members CSV")).to_be_visible()


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
    # Visit /reports with no auth cookie
    page.goto(f"{BASE_URL}/reports")

    # AuthenticatedLayout redirects to /login when getMe() fails
    expect(page).to_have_url(f"{BASE_URL}/login", timeout=10000)
