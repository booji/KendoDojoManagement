"""
Browser (Playwright) test stubs for issue #11 — Reports and CSV export.

These are red-phase xfail stubs — one per acceptance criterion.
Remove xfail and replace the body with real assertions once implementation is done.
"""

import pytest

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# AC1 — Reports UI renders attendance report with session data
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_reports_page_renders_attendance_report(page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC2 — Reports UI renders members report with grade and join date
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_reports_page_renders_members_report(page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC3 — CSV download buttons are present and trigger download
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_reports_page_has_csv_download_buttons(page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC4 — Reports page is navigable from the main UI (route exists)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_reports_page_is_accessible_via_navigation(page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC5 — Unauthenticated users are redirected away from the reports page
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_reports_page_redirects_unauthenticated_users(page) -> None:
    pytest.fail("not implemented")
