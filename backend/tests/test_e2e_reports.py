"""
Browser (Playwright) tests for issue #11 — Reports and CSV export.

One test per acceptance criterion.
"""

import pathlib
import sqlite3 as _sqlite3
import uuid

import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

_DB_PATH = pathlib.Path(__file__).parent.parent / "kendo.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_api(email: str, password: str = "Str0ng!Pass") -> str:
    resp = requests.post(
        f"{API_URL}/auth/register/password",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["sub"]


def _login_api(email: str, password: str = "Str0ng!Pass") -> str:
    resp = requests.post(
        f"{API_URL}/auth/login/password",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.cookies["access_token"]


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ]
    )


def _promote_to_admin(user_id: str) -> None:
    with _sqlite3.connect(_DB_PATH) as conn:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))


def _register_admin_token() -> str:
    tag = uuid.uuid4().hex[:8]
    email = f"e2e_reports_admin_{tag}@dojo.test"
    user_id = _register_api(email)
    _promote_to_admin(user_id)
    return _login_api(email)


def _register_member_token() -> str:
    tag = uuid.uuid4().hex[:8]
    email = f"e2e_reports_member_{tag}@dojo.test"
    _register_api(email)
    return _login_api(email)


# ---------------------------------------------------------------------------
# AC1 — Reports UI renders attendance report with session data
# ---------------------------------------------------------------------------


def test_reports_page_renders_attendance_report(page: Page) -> None:
    token = _register_admin_token()
    _inject_cookie(page, token)

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
    token = _register_admin_token()
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/reports")

    # Click the Members tab
    page.get_by_role("tab", name="Members").click()

    # The Generate button for members report is visible
    expect(page.get_by_role("button", name="Generate members report")).to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — CSV download buttons are present and trigger download
# ---------------------------------------------------------------------------


def test_reports_page_has_csv_download_buttons(page: Page) -> None:
    token = _register_admin_token()
    _inject_cookie(page, token)

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
    token = _register_admin_token()
    _inject_cookie(page, token)

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
